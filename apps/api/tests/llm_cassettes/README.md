# LLM cassettes

Responses the tests replay instead of calling the Anthropic API, one folder per
`{prompt_id}_v{version}`. A file holds exactly what the model would return as structured
output for that prompt's `OUTPUT_MODEL`.

**These were written by hand**, to match the synthetic fixture clips and to include
out-of-range values that the code must normalize. They are not recordings of real model
output. Replace them with recorded responses once an API key is available: run the
pipeline once and copy `llm_cache.output` for the matching prompt.
