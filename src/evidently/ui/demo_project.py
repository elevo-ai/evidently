import io
import warnings
import zipfile
from datetime import datetime
from datetime import time
from datetime import timedelta
from typing import Union

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta
from sklearn import ensemble

from evidently import ColumnMapping
from evidently import metrics
from evidently.report import Report
from evidently.test_preset import DataDriftTestPreset
from evidently.test_suite import TestSuite
from evidently.ui.dashboards import CounterAgg
from evidently.ui.dashboards import DashboardPanelCounter
from evidently.ui.dashboards import DashboardPanelPlot
from evidently.ui.dashboards import PanelValue
from evidently.ui.dashboards import PlotType
from evidently.ui.dashboards import ReportFilter
from evidently.ui.remote import RemoteWorkspace
from evidently.ui.workspace import Workspace
from evidently.ui.workspace import WorkspaceBase

warnings.filterwarnings("ignore")
warnings.simplefilter("ignore")

content = requests.get("https://archive.ics.uci.edu/static/public/275/bike+sharing+dataset.zip").content
with zipfile.ZipFile(io.BytesIO(content)) as arc:
    raw_data = pd.read_csv(
        arc.open("hour.csv"),
        header=0,
        sep=",",
        parse_dates=["dteday"],
        index_col="dteday",
    )

    raw_data.index = raw_data.apply(
        lambda row: datetime.combine(row.name, time(hour=int(row["hr"]))) + relativedelta(years=11),
        axis=1,
    )

reference = raw_data.loc["2023-01-01 00:00:00":"2023-01-28 23:00:00"]
current = raw_data.loc["2023-01-29 00:00:00":"2023-02-28 23:00:00"]

target = "cnt"
prediction = "prediction"
numerical_features = ["temp", "atemp", "hum", "windspeed", "hr", "weekday"]
categorical_features = ["season", "holiday", "workingday"]

column_mapping = ColumnMapping()
column_mapping.target = target
column_mapping.prediction = prediction
column_mapping.numerical_features = numerical_features
column_mapping.categorical_features = categorical_features

regressor = ensemble.RandomForestRegressor(random_state=0, n_estimators=50)
regressor.fit(reference[numerical_features + categorical_features], reference[target])

reference["prediction"] = regressor.predict(reference[numerical_features + categorical_features])
current["prediction"] = regressor.predict(current[numerical_features + categorical_features])

WORKSPACE = "workspace"
DEMO_PROJECT_NAME = "Demo Project"


def create_report(i: int, tags=[]):
    data_drift_report = Report(
        metrics=[
            metrics.RegressionQualityMetric(),
            metrics.DatasetSummaryMetric(),
            metrics.DatasetDriftMetric(),
            metrics.ColumnDriftMetric(column_name="cnt", stattest="wasserstein"),
            metrics.ColumnDriftMetric(column_name="prediction", stattest="wasserstein"),
            metrics.ColumnDriftMetric(column_name="temp", stattest="wasserstein"),
            metrics.ColumnDriftMetric(column_name="atemp", stattest="wasserstein"),
            metrics.ColumnDriftMetric(column_name="hum", stattest="wasserstein"),
            metrics.ColumnDriftMetric(column_name="windspeed", stattest="wasserstein"),
            metrics.ColumnSummaryMetric(column_name="cnt"),
            metrics.ColumnSummaryMetric(column_name="prediction"),
        ],
        timestamp=datetime(2023, 1, 29) + timedelta(days=i + 1),
    )
    data_drift_report.set_batch_size("daily")

    data_drift_report.run(
        reference_data=reference,
        current_data=current.loc[datetime(2023, 1, 29) + timedelta(days=i) : datetime(2023, 1, 29) + timedelta(i + 1)],
        column_mapping=column_mapping,
    )
    return data_drift_report


def create_test_suite(i: int, tags=[]):
    data_drift_test_suite = TestSuite(
        tests=[DataDriftTestPreset()],
        timestamp=datetime(2023, 1, 29) + timedelta(days=i + 1),
    )

    data_drift_test_suite.run(
        reference_data=reference,
        current_data=current.loc[datetime(2023, 1, 29) + timedelta(days=i) : datetime(2023, 1, 29) + timedelta(i + 1)],
        column_mapping=column_mapping,
    )
    return data_drift_test_suite


def create_project(workspace: WorkspaceBase):
    project = workspace.create_project(DEMO_PROJECT_NAME)
    project.description = "A toy demo project using Bike Demand forecasting dataset"
    project.dashboard.add_panel(
        DashboardPanelCounter(
            filter=ReportFilter(metadata_values={}, tag_values=[]),
            agg=CounterAgg.NONE,
            title="Bike Rental Demand Forecast",
        )
    )
    project.dashboard.add_panel(
        DashboardPanelCounter(
            title="Model Calls",
            filter=ReportFilter(metadata_values={}, tag_values=[]),
            value=PanelValue(
                metric_id="DatasetSummaryMetric",
                field_path=metrics.DatasetSummaryMetric.fields.current.number_of_rows,
                legend="count",
            ),
            text="count",
            agg=CounterAgg.SUM,
            size=1,
        )
    )
    project.dashboard.add_panel(
        DashboardPanelCounter(
            title="Share of Drifted Features",
            filter=ReportFilter(metadata_values={}, tag_values=[]),
            value=PanelValue(
                metric_id="DatasetDriftMetric",
                field_path="share_of_drifted_columns",
                legend="share",
            ),
            text="share",
            agg=CounterAgg.LAST,
            size=1,
        )
    )
    project.dashboard.add_panel(
        DashboardPanelPlot(
            title="Target and Prediction",
            filter=ReportFilter(metadata_values={}, tag_values=[]),
            values=[
                PanelValue(
                    metric_id="ColumnSummaryMetric",
                    field_path="current_characteristics.mean",
                    metric_args={"column_name.name": "cnt"},
                    legend="Target (daily mean)",
                ),
                PanelValue(
                    metric_id="ColumnSummaryMetric",
                    field_path="current_characteristics.mean",
                    metric_args={"column_name.name": "prediction"},
                    legend="Prediction (daily mean)",
                ),
            ],
            plot_type=PlotType.LINE,
            size=2,
        )
    )
    project.dashboard.add_panel(
        DashboardPanelPlot(
            title="MAE",
            filter=ReportFilter(metadata_values={}, tag_values=[]),
            values=[
                PanelValue(
                    metric_id="RegressionQualityMetric",
                    field_path=metrics.RegressionQualityMetric.fields.current.mean_abs_error,
                    legend="MAE",
                ),
            ],
            plot_type=PlotType.LINE,
            size=1,
        )
    )
    project.dashboard.add_panel(
        DashboardPanelPlot(
            title="MAPE",
            filter=ReportFilter(metadata_values={}, tag_values=[]),
            values=[
                PanelValue(
                    metric_id="RegressionQualityMetric",
                    field_path=metrics.RegressionQualityMetric.fields.current.mean_abs_perc_error,
                    legend="MAPE",
                ),
            ],
            plot_type=PlotType.LINE,
            size=1,
        )
    )
    project.dashboard.add_panel(
        DashboardPanelPlot(
            title="Features Drift (Wasserstein Distance)",
            filter=ReportFilter(metadata_values={}, tag_values=[]),
            values=[
                PanelValue(
                    metric_id="ColumnDriftMetric",
                    metric_args={"column_name.name": "temp"},
                    field_path=metrics.ColumnDriftMetric.fields.drift_score,
                    legend="temp",
                ),
                PanelValue(
                    metric_id="ColumnDriftMetric",
                    metric_args={"column_name.name": "atemp"},
                    field_path=metrics.ColumnDriftMetric.fields.drift_score,
                    legend="atemp",
                ),
                PanelValue(
                    metric_id="ColumnDriftMetric",
                    metric_args={"column_name.name": "hum"},
                    field_path=metrics.ColumnDriftMetric.fields.drift_score,
                    legend="hum",
                ),
                PanelValue(
                    metric_id="ColumnDriftMetric",
                    metric_args={"column_name.name": "windspeed"},
                    field_path=metrics.ColumnDriftMetric.fields.drift_score,
                    legend="windspeed",
                ),
            ],
            plot_type=PlotType.LINE,
            size=2,
        )
    )
    project.save()
    return project


def create_demo_project(workspace: Union[str, WorkspaceBase]):
    if isinstance(workspace, WorkspaceBase):
        ws = workspace
    else:
        if workspace.startswith("http"):
            ws = RemoteWorkspace(workspace)
        else:
            ws = Workspace.create(workspace)
    project = create_project(ws)

    for i in range(0, 28):
        report = create_report(i=i)
        ws.add_report(project.id, report)

        test_suite = create_test_suite(i=i)
        ws.add_test_suite(project.id, test_suite)


if __name__ == "__main__":
    # create_demo_project("http://localhost:8080")
    create_demo_project(WORKSPACE)