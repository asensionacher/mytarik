import json
from pydantic import BaseModel, ConfigDict, Field


class ExportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str
    output: str


def export_to_jsonl(results: list[ExportResult], filepath: str) -> None:
    with open(filepath, "a", encoding="utf-8") as f:
        for result in results:
            f.write(json.dumps(result.model_dump()) + "\n")


if __name__ == "__main__":
    results = [
        ExportResult(input="sample input 1", output="1234567890"),
        ExportResult(input="sample input 2", output="0987654321"),
        # Add more results as needed
    ]
    export_to_jsonl(results, "exported_data.jsonl")
