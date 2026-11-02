# Synthetic public fixtures

These files were **created for demonstration** and are not copies of the candidate's
customer database, internal manual or order export. Product names and IDs are fictional.

To evaluate against the provided challenge data, import the files locally with
`python -m app.cli --import-dir 'path/to/original/data'`.
The source directory can contain the original `desafio_tecnico_ai_eng - *.csv`
filenames. Never commit that directory.

The provided challenge dataset contains no reliable timestamp for promotions.
`is_active` is the explicit source of truth; a campaign name alone does not
establish current eligibility.

`people_fixture.csv` and `purchase_fixture.csv` contain made-up records with
reserved `.example` e-mail addresses. These allow the order-authorization
workflow to be demonstrated without exposing any challenge customer records.
