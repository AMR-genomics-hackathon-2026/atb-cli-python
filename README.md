# atb-cli

A Python CLI scaffold for **versioned, reproducible ATB queries** over parquet releases.

This rebuild uses:

- **`click`** for CLI argument handling
- **`pandas`** for CSV and parquet I/O (`pandas.read_parquet`)

It implements the workflow you described:

- `fetch`: fetch a parquet database for a specific ATB version
- `update`: update to the latest known release from a registry
- `versions`: inspect installed/current release metadata
- `query`: run a documented, reproducible query from a TOML file and write CSV output
- `summarise`: compute configurable summary statistics from a CSV
- `download`: download sequences for sample IDs/accessions in a CSV
- `run`: execute query + summarise + optional download in a single command

## Installation

From the project root:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
```

That installs the `atb` command.

## Suggested naming

- package/project name: `atb-cli`
- executable name: `atb`

That keeps the package discoverable while making the command short.

## Why this shape?

The scaffold is built around three goals:

1. **Reproducibility**
   - query filters live in TOML
   - every query writes a provenance JSON file
   - provenance captures the filter file digest, CLI version, and database version

2. **Versioned data access**
   - releases are defined in a registry JSON document
   - local state tracks the currently installed ATB parquet version
   - query results are explicitly tied to that version

3. **Clear extension points**
   - releases can be discovered directly from OSF or declared in a static registry
   - sequence download logic is driven by a URL template
   - summary output is configurable without editing code

## Registry format

By default, the CLI now points at your OSF storage page:

```text
https://osf.io/h7wzy/files/osfstorage
```

When the source is an OSF URL, `atb` uses the official OSF node-files API under the hood to enumerate files and discover `.parquet` releases dynamically. You can still override this with a static registry JSON if you want a stricter, curated release manifest.

Expected registry JSON shape when you use a static registry instead of OSF discovery:

```json
{
  "latest": "2026-03-01",
  "versions": {
    "2026-02-01": {
      "parquet_url": "https://data.example.org/atb/2026-02-01/atb.parquet",
      "checksum_sha256": "abc123...",
      "sequence_url_template": "https://api.example.org/sequences/{accession}.fasta",
      "release_date": "2026-02-01"
    },
    "2026-03-01": {
      "parquet_url": "https://data.example.org/atb/2026-03-01/atb.parquet",
      "checksum_sha256": "def456...",
      "sequence_url_template": "https://api.example.org/sequences/{accession}.fasta",
      "release_date": "2026-03-01"
    }
  }
}
```

## Commands

### Fetch a release

```bash
atb fetch
atb fetch --version 2026-03-01
atb fetch --registry https://osf.io/h7wzy/files/osfstorage
atb fetch --registry examples/registry.example.json --version 2026-03-01
```

If `--version` is omitted and the source is the default OSF page, the CLI fetches every discovered `.parquet` release and leaves the newest one as the current version. For static registry JSON sources, omitting `--version` still fetches only the latest declared version.

### Update to latest

```bash
atb update
atb update --registry https://osf.io/h7wzy/files/osfstorage
atb update --registry examples/registry.example.json
```

For the OSF source, `update` downloads every discovered parquet release newer than the current local version and then points `current_version` at the newest one. For static registry JSON sources, `update` still refreshes only the latest declared release.

### Inspect versions

```bash
atb versions
atb versions --version 2026-03-01
```

### Query with TOML filters

```bash
atb query \
  --filters examples/query.toml \
  --output results/query_results.csv \
  --provenance results/query_provenance.json
```

If your `current_version` points at an auxiliary parquet like `sylph` or `assembly`, `query` now looks for an installed parquet whose schema matches the requested filters and selected columns. You can still override that choice explicitly with `--version` or `--db-path`.

### Summarise query results

```bash
atb summarise \
  --input results/query_results.csv \
  --config examples/summarise.toml \
  --output results/summary.json
```

### Download sequences

```bash
atb download \
  --input results/query_results.csv \
  --output results/sequences.fasta \
  --accession-column sample_accession \
  --sequence-url-template 's3://allthebacteria-assemblies/<SAMPLE_ID>.fa.gz'
```

The downloader accepts standard `{accession}`-style templates and the ATB assembly template style with `<SAMPLE_ID>`. Public `s3://...` templates are fetched via the corresponding HTTPS S3 object URL, and `.fa.gz` payloads are decompressed automatically before being written to the output FASTA.
If you do not pass `--sequence-url-template`, `atb` now defaults to `s3://allthebacteria-assemblies/<SAMPLE_ID>.fa.gz`.
When the input CSV contains `sample_accession`, `atb` also checks the local `assembly` parquet for exact `aws_url` values and skips metadata-only samples that do not have a downloadable assembly FASTA.

### Run the whole pipeline

```bash
atb run \
  --filters examples/query.toml \
  --summary-config examples/summarise.toml \
  --output-dir results/run_01 \
  --max-samples 500 \
  --download \
  --accession-column sample_accession \
  --sequence-url-template 's3://allthebacteria-assemblies/<SAMPLE_ID>.fa.gz'
```

## Query TOML format

A query config contains one or more `[[filters]]` entries plus optional output controls.

Example:

```toml
select = [
  "sample_accession",
  "run_accession",
  "accession",
  "collection_date",
  "country",
  "scientific_name",
  "host",
  "instrument_platform",
  "library_strategy"
]

sort_by = ["collection_date", "sample_accession"]
distinct = true
limit = 1000

[[filters]]
column = "country"
op = "in"
value = ["USA", "United Kingdom"]

[[filters]]
column = "collection_date"
op = "between"
value = ["2024-01-01", "2024-12-31"]

[[filters]]
column = "instrument_platform"
op = "eq"
value = "ILLUMINA"
```

The bundled example targets the main date-based ATB parquet releases such as `2025-05-06`, which contain columns like `sample_accession`, `run_accession`, `accession`, `collection_date`, `country`, `scientific_name`, `host`, `instrument_platform`, and `library_strategy`.
You can optionally add a `scientific_name` filter if you want to narrow the query to a single species.

Supported operators:

- `eq`
- `ne`
- `in`
- `not_in`
- `gt`
- `gte`
- `lt`
- `lte`
- `between`
- `contains`
- `startswith`
- `endswith`
- `is_null`
- `not_null`

## Summary TOML format

If omitted, `summarise` uses sensible defaults when the columns exist.

Example:

```toml
[summary]
id_column = "sample_accession"
date_columns = ["collection_date"]
categorical_columns = ["country", "instrument_platform", "scientific_name"]
custom_columns = ["host", "library_strategy"]
top_n = 15
```

## Provenance output

Each `query` writes a JSON file that captures:

- CLI version
- UTC execution timestamp
- filter TOML path
- SHA-256 hash of the filter TOML
- canonicalized query config
- database path
- database version
- database release metadata
- result CSV path
- row count
- optional pipeline-level sample limit

That gives you a direct record of **how the sample set was created**.

## Local storage layout

By default, data is stored under:

```text
~/.local/share/atb-cli/
```

Override this with:

```bash
export ATB_CLI_HOME=/path/to/custom/location
```

Expected layout:

```text
ATB_CLI_HOME/
  db/
    2026-03-01/
      atb.parquet
      metadata.json
  state/
    state.json
```

## Notes

- `query` reads parquet with **`pandas.read_parquet(...)`**.
- In practice, that means you should keep `pyarrow` installed.
- The sequence download endpoint is deliberately template-based so you can plug in the real ATB API later.


## OSF source behavior

For your current setup, the default source is the OSF project page you sent:

```text
https://osf.io/h7wzy/files/osfstorage
```

The CLI converts that into the OSF API endpoint for listing node files:

```text
https://api.osf.io/v2/nodes/h7wzy/files/osfstorage/
```

It then scans the returned files for names ending in `.parquet`, infers a release version from the filename, and uses the OSF file download link for `fetch`. When you run `atb fetch` against that OSF source without `--version`, it downloads every discovered parquet file. This is based on the documented OSF node-files endpoint shape and pagination model, and on OSF's project files pages for public projects.

Version inference tries these patterns in order:

- `YYYY-MM-DD`
- `YYYYMMDD`
- semantic versions like `v1.2.3`
- otherwise the filename stem

So filenames like these work well:

```text
atb_2026-03-01.parquet
atb_20260301.parquet
atb_v1.2.3.parquet
```

For best reproducibility, date-based names are the clearest option.
