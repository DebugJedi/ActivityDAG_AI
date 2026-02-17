# Quick Start Checklist

## Pre-Deployment (One-time setup)

- [ ] **Azure CLI installed**
  ```powershell
  npm install -g azure-functions-core-tools@4 --unsafe-perm=true
  npm install -g @azure/static-web-apps-cli
  ```

- [ ] **Azure Subscription ready** with payment method

- [ ] **GitHub repository created** with this code pushed
  - [ ] Repo is public (or you have permissions)
  - [ ] Create GitHub Personal Access Token: https://github.com/settings/tokens/new
    - Scopes: `public_repo`, `workflow` (optional)

- [ ] **Azure OpenAI Resource created** (or OpenAI API key obtained)
  - Model: gpt-4o-mini (or your choice)

---

## Phase 1: Deploy Azure Infrastructure (15-20 minutes)

```powershell
cd c:\mygit\CriticalPath-AI-E2

# Run deployment script
.\scripts\deploy-azure.ps1
```

**Inputs you'll need:**
- Azure Subscription ID
- Resource Group name: `criticalpath-rg`
- Region: `eastus` (or your preferred region)
- Function App name: `cp-api-` + your initials
- Storage Account name: `cpapistg` (must be globally unique)
- Static Web App name: `cp-app-swa`
- Azure OpenAI API Key
- Azure OpenAI Endpoint (format: `https://your-resource.openai.azure.com/`)
- GitHub repo URL
- GitHub Personal Access Token

**Outputs to save:**
- [ ] Azure Storage Connection String
- [ ] Static Web App deployment token (check Azure portal)
- [ ] Function App name
- [ ] Static Web App URL

---

## Phase 2: Local Testing (Every time you test)

**Terminal 1** - Backend:
```powershell
cd c:\mygit\CriticalPath-AI-E2
.\scripts\run-local.ps1
```
- Provide API key when prompted
- Should see: `Azure Functions Core Tools (4.x.x)`
- Backend ready at: `http://localhost:7071`

**Terminal 2** - Frontend (Optional - for local UI testing):
```powershell
cd c:\mygit\CriticalPath-AI-E2\frontend
python -m http.server 8080
```
- Frontend ready at: `http://localhost:8080`

**Test endpoints:**
```powershell
# Projects
curl http://localhost:7071/api/projects

# Create session
curl -X POST http://localhost:7071/api/session ^
  -H "Content-Type: application/json" ^
  -d '{"proj_id":"P01-1"}'
```

---

## Phase 3: Deploy Frontend to Azure

```powershell
cd c:\mygit\CriticalPath-AI-E2

# Push code to GitHub
git add .
git commit -m "Deploy frontend to Azure"
git push origin main

# Wait 2-5 minutes for GitHub Actions to build and deploy
# Check: https://github.com/YOUR-USERNAME/CriticalPath-AI-E2/actions
```

**Verify:**
- [ ] GitHub Actions workflow completed (green checkmark)
- [ ] Visit Static Web App URL (from Azure portal or GitHub output)
- [ ] Frontend loads and shows project selector
- [ ] Check browser console (F12) for errors

---

## Phase 4: Test Full Application

1. **Local Backend** must still be running (`.\scripts\run-local.ps1`)
2. **Open Static Web App URL** in browser
3. **Test workflow:**
   - [ ] Load projects (dropdown should populate)
   - [ ] Start session (click "Start Session")
   - [ ] Send query ("Show critical path")
   - [ ] Receive response with analysis

**If it fails:**
- Check browser console (F12) for errors
- Verify backend is still running on `localhost:7071`
- Check Azure Storage has CSV files uploaded

---

## Optional: Deploy Backend to Azure (Production)

**Only do this after testing locally works!**

```powershell
.\scripts\deploy-functions.ps1
```

Then update Static Web App to point to Azure Function App endpoint instead of localhost.

---

## Hosting Plan Summary

| Component | Azure Plan | Monthly Cost | Limits |
|-----------|-----------|--------------|--------|
| **Static Web Apps** | Free Tier | $0 | 1 app, 1 custom domain |
| **Function App** | Consumption | ~$0-5 | Pay per execution |
| **Blob Storage** | Standard LRS | ~$1-5 | Pay per GB |
| **Azure OpenAI** | Pay-as-you-go | ~$5-50 | ~$0.003/1K tokens |
| **TOTAL ESTIMATE** | | **$5-60/month** | Good for MVP |

---

## Estimated Timeline

| Task | Time | Notes |
|------|------|-------|
| Azure setup | 15-20 min | One-time |
| Local testing | 5 min | Each session |
| Frontend deployment | 2-5 min | GitHub Actions |
| Full testing | 10 min | On Azure |
| **TOTAL FIRST TIME** | **~45 min** | After that: 5 min per test |

---

## File Structure After Deployment

```
Your PC                          Azure Cloud
├── api/                         ├── Static Web Apps
│   ├── chat/                    │   ├── frontend/
│   ├── projects/                │   └── index.html
│   ├── session/
│   ├── shared/
│   └── host.json (v4.0)         ├── Blob Storage
│                                 │   └── project-data/
├── frontend/                     │       └── CSV files
│   ├── app.js
│   ├── index.html
│   └── styles.css               ├── Function App
│                                 │   (deployed later if needed)
└── data/
    └── CSV files (uploaded to blob)
```

---

## Support & Debugging

**Check logs:**
```powershell
# Function App logs
func azure functionapp logstream <function-app-name>

# Static Web App logs (GitHub Actions)
# Visit: https://github.com/YOUR-USERNAME/CriticalPath-AI-E2/actions
```

**Common Issues:**
1. "API not found" → Backend not running locally
2. "404 on frontend" → GitHub Actions failed, check logs
3. "CORS error" → Should not happen, check browser console
4. "No projects showing" → CSV files not in Blob Storage

---

## Next: You Are Here 👇

- [x] Step 1: Identified Azure resources needed
- [x] Step 2: Deployment guide created
- [ ] **NOW:** Run `.\scripts\deploy-azure.ps1`
- [ ] Test locally with `.\scripts\run-local.ps1`
- [ ] Deploy frontend (git push)
- [ ] Test on Azure
