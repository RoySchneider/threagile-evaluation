# threagile-evaluation

Threat modeling with Threagile as a stage of a GitLab pipeline. Unhandled risks trigger a warning, and the pipeline continues.

| File | Contents |
|---|---|
| `.gitlab-ci.yml` | Pipeline with the jobs `threagile-analyze` and `threagile-evaluate` |
| `ci/evaluate_threagile_risks.py` | Evaluation of `risks.json` |
| `threat-model/threagile-example-model.yaml` | Example model from Threagile 0.9.1 (`demo/example/threagile.yaml`, in the image as `/app/threagile-example-model.yaml`), unmodified; input of the pipeline |

## Exit codes of `evaluate_threagile_risks.py`

| Code | Meaning | In the pipeline |
|---|---|---|
| 0 | no unhandled risks | green |
| 3 | unhandled risks (status `unchecked` or `in-discussion`), at most `elevated` | warning |
| 4 | at least one unhandled risk `high` or `critical` | warning |
| 1 | evaluation not possible: file missing, invalid JSON, unknown status or severity | job fails |

Codes 3 and 4 are listed in `allow_failure:exit_codes`. The script also writes `gl-code-quality-report.json`, which GitLab shows in the merge request.

## Running locally (PowerShell)

```powershell
New-Item -ItemType Directory -Force threagile-output | Out-Null
docker run --rm -v "${PWD}:/app/work" threagile/threagile:latest `
  -verbose -model /app/work/threat-model/threagile-example-model.yaml -output /app/work/threagile-output
python ci\evaluate_threagile_risks.py --risks threagile-output\risks.json `
  --model threat-model/threagile-example-model.yaml --codequality gl-code-quality-report.json
echo $LASTEXITCODE
```

Note on versions: on Docker Hub, `threagile/threagile:latest` is the same image as `0.9.1` (as of 2026-10-23). The `-model`/`-output` invocation and the example model from 0.9.1 match it. The development state in the repository (version 1, no published image) expects `threagile analyze-model --model … --output …` and partly different values in the model, e.g. `end-user-identity-propagation` instead of `enduser-identity-propagation`. Pin the image by digest before use.

## Origin of the example model

Threagile, https://github.com/Threagile/threagile, version 0.9.1. MIT license, Copyright (c) 2020 Christian Schneider; license text in `threat-model/LICENSE-threagile.txt`.
