# ETCS Level 3 Requirement Extractor

Extracts the requirements of railway specification PDFs (X2Rail-1/3/5, R2DATO) into
Excel: topic, ID, description (with its figures and tables) and traceability.

## Setup

Create the virtual environment:

```
python -m venv venv
```

Activate it (PowerShell):

```
venv\Scripts\Activate.ps1
```

Install the requirements:

```
pip install -r requirements.txt
```

The PDFs and the manual references are not in the repository. Copy them into:

- `input/` : `X2R1.pdf`, `X2R3.pdf`, `X2R5.pdf`, `R2DATO_V1.pdf`, `R2DATO_V2.pdf`
- `reference/` : the five `*_Requirements*.xlsx` files

## Usage

With the environment activated:

```
python src\extractor.py                    # all documents
python src\extractor.py X2R3 R2DATO_V1     # some of them
python src\extractor.py input\X2R5.pdf output\X2R5_Result.xlsx X2R5
```

Results go to `output/`, one Excel file per document. Each run ends with a
comparison with the manual reference; every difference is written to
`output/extractor.log`.

## Tests

```
python -m pytest tests
```

## Adding a document

Add a `[[documents]]` block to `config.toml`. If its requirement IDs have a new
format, add the pattern to `[ids]`.

## License

MIT License. See [LICENSE](LICENSE).