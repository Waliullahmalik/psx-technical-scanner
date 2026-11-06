# Google Cloud Run deployment — PSX Technical Scanner v3.5

## What this deploys
This is the existing v3.4 Streamlit application with a **read-only public viewer mode**. Public visitors can scan, filter and inspect charts, but cannot upload, correct or delete CSV files, nor initiate PSX requests. It starts with the bundled `data/FFC.csv` demo history.

## Bring your real 100-company dataset
**Before deploying**, copy the 100 `*.csv` files from your current working scanner's `data/` folder into this package's `data/` folder. Check redistribution rights first: deploying the CSVs into a publicly accessible service exposes derived values, so only include market data you are authorized to serve or make public. Do not include accounts, secrets, cookies, proprietary files or credentials.

If a data source forbids redistribution/public algorithmic usage, deploy privately or obtain appropriate rights.

## Requirements
- Google Cloud account and a billing-enabled project (free tier is not a hard spending limit).
- Google Cloud CLI (`gcloud`) installed locally.
- IAM access to deploy a Cloud Run service.
- Confirm the permitted usage rights for your underlying price data.

## Deploy from Windows PowerShell
In this extracted directory run:

```powershell
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
gcloud run deploy psx-technical-scanner --source . --region asia-south1 --allow-unauthenticated --min-instances 0 --max-instances 1 --memory 1Gi --cpu 1 --concurrency 10 --timeout 900
```

If the environment rejects an authorization flag, use the Google Cloud Console -> Cloud Run -> service -> Security -> Allow public access (subject to organization policy).

Google prints an HTTPS `run.app` URL. Open it on your phone and share it with friends. The first load may take longer after an idle period.

## Important limitation — persistent data
Cloud Run instances are **stateless**. Changes written to local disk are temporary and different instances don't share them. Therefore this deployment **bundles market data into the image** and disables public editing. To update price histories, modify your local data/ files and rerun the same `gcloud run deploy ... --source .` command. This also publishes the latest included live snapshot if you add one in `output/live/`. Do not assume a public visitor's Fetch button would persist (there is no public Fetch button).

For a later automatic-update version, use private Cloud Storage (or Firestore) with an authenticated admin workflow and only publish signals licensed for distribution.

## Cost and access
Cloud Run has monthly free usage allowances, **not guaranteed zero-cost hosting**. Google Cloud requires billing setup; Cloud Build, Artifact Registry storage, network egress and usage above free allowances can cost money. Configure Google Cloud Billing -> Budgets & alerts. Prefer min-instances=0, max-instances=1 for an initial low-traffic deployment.

## Security
The app is public when `--allow-unauthenticated` succeeds. Do not expose data editing to unauthenticated visitors. Future updates should use IAM/authentication. For a friends-only deployment, avoid public mode and use an access-controlled front end; Cloud Run IAM alone can be awkward for browser-based Streamlit.

## Running locally
```powershell
python -m pip install -r requirements.txt
$env:PSX_PUBLIC_VIEW="1"
python -m streamlit run app.py
```
This tests the same read-only UI locally, without cloud deployment.
