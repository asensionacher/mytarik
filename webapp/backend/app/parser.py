import re
from pydantic import BaseModel, ConfigDict, Field


class ParsingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str
    output: str


def extract_taric_codes(text: str) -> list[ParsingResult]:
    pattern = r"\b\d{10}\b"
    matches = re.finditer(pattern, text)
    results = []
    for match in matches:
        start, end = match.span()
        context = text[max(0, start - 50):end + 50]
        results.append(ParsingResult(input=context, output=match.group()))
    return results


if __name__ == "__main__":
    text = "This is a sample text with TARIC codes like 1234567890 and 0987654321."
    parsed_results = extract_taric_codes(text)
    for result in parsed_results:
        print(f"Input: {result.input}\nOutput: {result.output}\n")
