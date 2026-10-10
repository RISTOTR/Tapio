"""Strict typed source facts; enrichments are validated separately by the loader."""

import pandera.polars as pa
import polars as pl

bank_schema = pa.DataFrameSchema(
    {
        "booking_date": pa.Column(pl.Date),
        "value_date": pa.Column(pl.Date, nullable=True),
        "amount": pa.Column(pl.Decimal(20, 6), checks=pa.Check.ne(0)),
        "currency": pa.Column(pl.String, checks=pa.Check.eq("EUR")),
        "direction": pa.Column(pl.String, checks=pa.Check.isin(["incoming", "outgoing"])),
        **{
            key: pa.Column(pl.String, nullable=True)
            for key in [
                "raw_counterparty",
                "reference",
                "message",
                "transaction_type_code",
            ]
        },
        **{
            key: pa.Column(pl.String, checks=pa.Check.str_length(min_value=1))
            for key in [
                "source_file",
                "source_transaction_id",
                "raw_source",
            ]
        },
    },
    strict=False,
    coerce=False,
)

bank_enriched_schema = pa.DataFrameSchema(
    {
        **bank_schema.columns,
        **{
            key: pa.Column(pl.String, nullable=True)
            for key in [
                "normalized_counterparty",
                "payment_intermediary",
                "ultimate_recipient",
            ]
        },
        "category": pa.Column(
            pl.String,
            checks=pa.Check.isin(
                [
                    "unknown",
                    "electricity",
                    "grid_distribution",
                    "forestry_service",
                    "timber_income",
                    "tax",
                ]
            ),
        ),
        "business_context": pa.Column(
            pl.String,
            checks=pa.Check.isin(
                [
                    "unknown",
                    "property",
                    "forestry",
                    "personal",
                ]
            ),
        ),
        "rule_metadata": pa.Column(pl.String, checks=pa.Check.str_length(min_value=1)),
    },
    strict=True,
    coerce=False,
)
