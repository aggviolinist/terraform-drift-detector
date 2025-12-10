# terraform-drift-detector
Python code to detect drift detection on terraform state file
## Activate the Python Environment
```sh
python3 -m venv venv
source venv/bin/activate
```
```sh
python -m pip install deepdiff
```
## Step 1: Create a plan file
```sh
terraform plan -out=tfplan
```
## Step 2: Convert to json
```sh
terraform show -json tfplan > plan.json
```
### Step 3: Run the script
```sh
python drift-detector.py terraform.tfstate plan.json
```

