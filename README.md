# Tandem Deal Logger

Upload a PDF deal list → auto-logs every company to Affinity Active Pipeline.

## Files
```
deal-logger/
├── public/index.html      ← the web UI
├── api/log-deals.py       ← serverless backend
├── vercel.json            ← Vercel config
├── requirements.txt       ← Python deps
└── README.md
```

## Deploy to Vercel (5 minutes)

### Step 1 — Push to GitHub
1. Go to github.com → New repository → name it `tandem-deal-logger`
2. Upload all these files (drag and drop works)
3. Click Commit

### Step 2 — Deploy on Vercel
1. Go to vercel.com → Add New Project
2. Import your `tandem-deal-logger` GitHub repo
3. Click Deploy (don't change any settings)

### Step 3 — Add Environment Variables
In your Vercel project → Settings → Environment Variables, add:

| Name | Value |
|------|-------|
| `AFFINITY_API_KEY` | Your Affinity API key |
| `AFFINITY_LIST_ID` | Your pipeline list ID (from the URL in Affinity) |
| `ANTHROPIC_API_KEY` | Your Anthropic API key (from console.anthropic.com) |

Then go to Deployments → Redeploy so the env vars take effect.

### Step 4 — Done
Bookmark your Vercel URL. Every time you have deals to log:
1. Open the URL
2. Upload your PDF
3. Hit "Log Deals to Affinity"

## How to find your List ID
Open your Active Pipeline in Affinity.
The URL will look like: `affinity.co/lists/123456`
Copy that number — that's your List ID.

## How to get your Anthropic API Key
Go to console.anthropic.com → API Keys → Create Key
