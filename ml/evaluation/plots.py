"""Private, generated matplotlib artifacts; never product charts."""

import os
from pathlib import Path

import polars as pl


def save_plots(
    rows: pl.DataFrame, daily: pl.DataFrame, hourly_errors: pl.DataFrame, output: Path
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(output / "matplotlib-cache"))
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["timezone"] = "Europe/Helsinki"
    import matplotlib.pyplot as plt

    names = ["seasonal_naive", "ridge", "hist_gradient_boosting"]
    fig, ax = plt.subplots(figsize=(11, 4))
    first = rows.filter(pl.col("model") == names[0]).head(168)
    dates = first["timestamp"].dt.convert_time_zone("Europe/Helsinki").to_list()
    ax.plot(dates, first["consumption_kwh"], label="Actual", color="black", linewidth=1)
    for name in names:
        data = rows.filter(pl.col("model") == name).head(168)
        ax.plot(dates, data["prediction"], label=name, alpha=0.7, linewidth=0.8)
    ax.set(
        title="First test week: rolling one-hour-ahead predictions",
        ylabel="Consumption (kWh)",
        xlabel="Time (Europe/Helsinki)",
    )
    ax.legend(fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output / "actual_vs_predicted.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4))
    for name in names:
        values = rows.filter(pl.col("model") == name)["residual"]
        ax.hist(values, bins=50, histtype="step", label=name, density=True)
    ax.set(xlabel="Actual - predicted (kWh)", ylabel="Density", title="Test residual distributions")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output / "residual_distribution.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4))
    for name in names:
        part = hourly_errors.filter(pl.col("model") == name)
        ax.plot(part["hour_of_day"], part["mae_kwh"], marker=".", label=name)
    ax.set(
        xlabel="Hour of day (Europe/Helsinki)", ylabel="MAE (kWh)", title="Test error by local hour"
    )
    ax.legend()
    fig.tight_layout()
    fig.savefig(output / "mae_by_hour.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.scatter(daily["daily_mean_temperature_c"], daily["daily_consumption_kwh"], s=10, alpha=0.4)
    ax.set(
        xlabel="Observed daily mean temperature (°C)",
        ylabel="Daily consumption (kWh)",
        title="Descriptive daily association (complete local days, not causal)",
    )
    fig.tight_layout()
    fig.savefig(output / "daily_temperature_consumption.png", dpi=160)
    plt.close(fig)
