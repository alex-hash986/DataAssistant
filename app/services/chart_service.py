from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from app.core.config import Settings, get_settings
from app.services.file_service import FileReadError, FileService, StoredFile


logger = logging.getLogger(__name__)


class ChartService:
    def __init__(self, file_service: FileService, settings: Settings | None = None) -> None:
        self.file_service = file_service
        self.settings = settings or get_settings()

    def generate_chart(
        self,
        stored_file: StoredFile,
        chart_type: str,
        x_column: str | None = None,
        y_column: str | None = None,
    ) -> dict[str, Any]:
        chart_type = chart_type.lower()
        if chart_type not in {"line", "bar", "histogram", "pie"}:
            raise FileReadError("Поддерживаются только графики line, bar, histogram и pie.")
        if chart_type == "pie" and stored_file.kind != "table":
            raise FileReadError("Круговая диаграмма доступна только для таблиц.")

        self.file_service.ensure_storage()
        if stored_file.kind == "table":
            chart = self._generate_table_chart(stored_file, chart_type, x_column, y_column)
        else:
            chart = self._generate_image_chart(stored_file, chart_type)

        logger.info("Generated %s chart for %s", chart_type, stored_file.file_id)
        return chart

    def generate_default_charts(self, stored_file: StoredFile) -> list[dict[str, Any]]:
        charts: list[dict[str, Any]] = []
        for chart_type in ("histogram", "bar"):
            try:
                charts.append(self.generate_chart(stored_file, chart_type))
            except FileReadError:
                continue
        return charts

    def _generate_table_chart(
        self,
        stored_file: StoredFile,
        chart_type: str,
        x_column: str | None,
        y_column: str | None,
    ) -> dict[str, Any]:
        dataframe = self.file_service.read_dataframe(stored_file)
        columns = self.file_service.describe_columns(dataframe)
        numeric_columns = [item["name"] for item in columns if item["kind"] == "numeric"]
        dimension_columns = [item["name"] for item in columns if item["kind"] in {"categorical", "datetime"}]

        if chart_type == "pie":
            return self._generate_pie_chart(
                stored_file,
                dataframe,
                x_column or (dimension_columns or list(dataframe.columns))[0],
                y_column or next(iter(numeric_columns), None),
            )

        selected_x = x_column or (dimension_columns or list(dataframe.columns))[0]
        selected_y = y_column or (numeric_columns or list(dataframe.columns))[0]
        file_name = self._build_output_name(stored_file.file_id, chart_type, "png")
        output_path = self.settings.output_dir / file_name

        figure, axis = plt.subplots(figsize=(10, 5.8), dpi=150)
        figure.patch.set_facecolor("#f8f3ea")
        axis.set_facecolor("#fffaf3")

        if chart_type == "histogram":
            if not numeric_columns:
                raise FileReadError("Для histogram нужен хотя бы один числовой столбец.")
            selected_x = x_column or numeric_columns[0]
            series = pd.to_numeric(dataframe[selected_x], errors="coerce").dropna()
            if series.empty:
                raise FileReadError("Недостаточно числовых значений для histogram.")
            bins = min(20, max(8, int(np.sqrt(len(series)))))
            axis.hist(series, bins=bins, color="#d06b4e", edgecolor="#8d3f28")
            axis.set_title(f"Histogram: {selected_x}")
            axis.set_xlabel(selected_x)
            axis.set_ylabel("Frequency")
            description = f"Распределение значений колонки «{selected_x}»."
        elif chart_type == "line":
            if not numeric_columns:
                raise FileReadError("Для line нужен хотя бы один числовой столбец.")
            plot_frame = dataframe[[selected_x, selected_y]].copy()
            plot_frame[selected_y] = pd.to_numeric(plot_frame[selected_y], errors="coerce")
            plot_frame = plot_frame.dropna(subset=[selected_y]).head(50)
            if plot_frame.empty:
                raise FileReadError("Недостаточно данных для line графика.")
            axis.plot(
                plot_frame[selected_x].astype(str),
                plot_frame[selected_y],
                color="#114b5f",
                linewidth=2.5,
                marker="o",
            )
            axis.set_title(f"Line chart: {selected_y} by {selected_x}")
            axis.set_xlabel(selected_x)
            axis.set_ylabel(selected_y)
            axis.tick_params(axis="x", rotation=35)
            description = f"Линейная динамика «{selected_y}» по оси «{selected_x}»."
        else:
            if numeric_columns:
                group_x = x_column or (dimension_columns or list(dataframe.columns))[0]
                group_y = y_column or numeric_columns[0]
                grouped = (
                    dataframe[[group_x, group_y]]
                    .copy()
                    .dropna(subset=[group_x, group_y])
                    .groupby(group_x, dropna=True)[group_y]
                    .mean()
                    .sort_values(ascending=False)
                    .head(12)
                )
                if grouped.empty:
                    raise FileReadError("Недостаточно данных для bar графика.")
                axis.bar(grouped.index.astype(str), grouped.values, color="#6c8b6b")
                axis.set_ylabel(f"Mean {group_y}")
                axis.set_title(f"Bar chart: {group_x}")
                description = f"Средние значения «{group_y}» по категориям «{group_x}»."
            else:
                counts = dataframe[selected_x].astype(str).value_counts().head(12)
                axis.bar(counts.index, counts.values, color="#6c8b6b")
                axis.set_ylabel("Count")
                axis.set_title(f"Bar chart: {selected_x}")
                description = f"Частоты по колонке «{selected_x}»."
            axis.tick_params(axis="x", rotation=30)

        figure.tight_layout()
        figure.savefig(output_path, bbox_inches="tight")
        plt.close(figure)
        return {
            "title": f"{chart_type.title()} chart",
            "description": description,
            "file_name": file_name,
            "relative_path": f"outputs/{file_name}",
            "storage_url": f"/storage/outputs/{file_name}",
            "download_url": f"/download/{file_name}",
        }

    def _generate_pie_chart(
        self, stored_file: StoredFile, dataframe: pd.DataFrame, x_column: str, y_column: str | None
    ) -> dict[str, Any]:
        for column in (x_column, y_column):
            if column is not None and column not in dataframe.columns:
                raise FileReadError(f"Колонка «{column}» не найдена.")

        categories = dataframe[x_column].astype("string").str.strip()
        categories = categories.mask(categories == "", "(без категории)").fillna("(без категории)")
        if y_column is None:
            grouped = categories.value_counts()
            description = f"Доли по количеству строк для «{x_column}»."
        else:
            values = pd.to_numeric(dataframe[y_column], errors="coerce").astype("float64")
            valid = np.isfinite(values)
            if (values[valid] < 0).any():
                raise FileReadError(f"Круговая диаграмма требует неотрицательных значений в «{y_column}».")
            grouped = values[valid].groupby(categories[valid]).sum().sort_values(ascending=False)
            description = f"Доли суммы «{y_column}» по «{x_column}»."
            skipped = int((~valid).sum())
            if skipped:
                description += f" Пропущено строк с пропущенными или некорректными значениями: {skipped}."

        grouped = grouped[grouped > 0]
        total = grouped.sum()
        if not np.isfinite(total) or total <= 0:
            raise FileReadError("Для круговой диаграммы нужна положительная конечная сумма.")

        labels = grouped.index[:8].tolist()
        amounts = grouped.iloc[:8].tolist()
        if len(grouped) > 8:
            labels.append(f"Остальные категории ({len(grouped) - 8})")
            amounts.append(grouped.iloc[8:].sum())
        shares = [amount / total for amount in amounts]
        legend = [
            f"{label if len(label) <= 44 else label[:43] + '…'} — {amount:,.6g} ({share:.1%})"
            for label, amount, share in zip(labels, amounts, shares)
        ]

        file_name = self._build_output_name(stored_file.file_id, "pie", "png")
        figure, axis = plt.subplots(figsize=(10, 5.8), dpi=150)
        try:
            figure.patch.set_facecolor("#f8f3ea")
            wedges, _ = axis.pie(shares, startangle=90, wedgeprops={"edgecolor": "#f8f3ea"})
            axis.legend(wedges, legend, loc="center left", bbox_to_anchor=(1, 0.5), frameon=False)
            axis.set_title(f"Доли по «{x_column}»")
            figure.tight_layout()
            figure.savefig(self.settings.output_dir / file_name, bbox_inches="tight")
        finally:
            plt.close(figure)
        return {
            "title": "Круговая диаграмма",
            "description": description,
            "file_name": file_name,
            "relative_path": f"outputs/{file_name}",
            "storage_url": f"/storage/outputs/{file_name}",
            "download_url": f"/download/{file_name}",
        }

    def _generate_image_chart(self, stored_file: StoredFile, chart_type: str) -> dict[str, Any]:
        image = self.file_service.open_image(stored_file)
        array = np.array(image)
        grayscale = np.array(image.convert("L"))
        file_name = self._build_output_name(stored_file.file_id, chart_type, "png")
        output_path = self.settings.output_dir / file_name

        figure, axis = plt.subplots(figsize=(10, 5.8), dpi=150)
        figure.patch.set_facecolor("#f8f3ea")
        axis.set_facecolor("#fffaf3")

        if chart_type == "histogram":
            axis.hist(grayscale.ravel(), bins=32, color="#d06b4e", edgecolor="#8d3f28")
            axis.set_title("Pixel intensity histogram")
            axis.set_xlabel("Intensity")
            axis.set_ylabel("Pixels")
            description = "Распределение интенсивности пикселей изображения."
        elif chart_type == "bar":
            if array.ndim == 2:
                labels = ["L"]
                values = [grayscale.mean()]
                colors = ["#114b5f"]
            else:
                labels = list(image.getbands())
                values = [array[:, :, index].mean() for index in range(array.shape[2])]
                colors = ["#114b5f", "#6c8b6b", "#d06b4e", "#8d3f28"][: len(labels)]
            axis.bar(labels, values, color=colors)
            axis.set_title("Mean channel values")
            axis.set_ylabel("Average value")
            description = "Средние значения по каналам изображения."
        else:
            profile = grayscale.mean(axis=0)
            axis.plot(np.arange(len(profile)), profile, color="#114b5f", linewidth=2.0)
            axis.set_title("Horizontal brightness profile")
            axis.set_xlabel("X coordinate")
            axis.set_ylabel("Average brightness")
            description = "Средняя яркость по горизонтальной оси изображения."

        figure.tight_layout()
        figure.savefig(output_path, bbox_inches="tight")
        plt.close(figure)
        return {
            "title": f"{chart_type.title()} chart",
            "description": description,
            "file_name": file_name,
            "relative_path": f"outputs/{file_name}",
            "storage_url": f"/storage/outputs/{file_name}",
            "download_url": f"/download/{file_name}",
        }

    def _build_output_name(self, file_id: str, artifact_type: str, extension: str) -> str:
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S")
        return f"{file_id}__{artifact_type}__{timestamp}.{extension}"
