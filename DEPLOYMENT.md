# CriticalPath AI - Deployment Guide

## Overview

This guide covers **two deployment scenarios**:
1. **LOCAL TESTING** - Backend runs on your machine, frontend for testing
2. **AZURE PRODUCTION** - Frontend on Azure Static Web Apps, backend stays local (or can be moved to Azure later)

---

## 📋 Prerequisites

### Required Tools

```powershell
# Install Azure CLI
# Download from: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli-windows

# Install Azure Functions Core Tools
npm install -g azure-functions-core-tools@4 --unsafe-perm=true

# Install Azure Static Web Apps CLI
npm install -g @azure/static-web-apps-cli

# Verify installations
az --version
func --version
swa --version
```

### Required Azure Resources (to be created)
- ✅ Azure Subscription (with credits/payment method)
- ✅ Azure OpenAI Service (or OpenAI API key)
- ✅ Resource Group
- ✅ Storage Account (for CSV data)
- ✅ Function App (for backend - needed later)
- ✅ Static Web App (for frontend hosting)

### GitHub Repository
- Code must be pushed to GitHub (for Static Web App CI/CD)
- Generate GitHub Personal Access Token: https://github.com/settings/tokens

---

## 🚀 Step 1: Setup Azure Resources (First Time Only)

### Run the Azure Setup Script

This script creates all necessary Azure resources and uploads your data.

```powershell
cd c:\mygit\CriticalPath-AI-E2
.\scripts\deploy-azure.ps1
```

**The script will prompt for:**
1. Azure Subscription ID
2. Resource Group name (e.g., `criticalpath-rg`)
3. Azure Region (e.g., `eastus`)
4. Function App name (e.g., `cp-api-func`)
5. Storage Account name (e.g., `cpapistg`)
6. Static Web App name (e.g., `cp-app-swa`)
7. Azure OpenAI API Key
8. Azure OpenAI Endpoint
9. GitHub Repository URL
10. GitHub Personal Access Token

**Output:** Connection string (save this in a safe place!)

---

## 💻 Step 2: Run Backend Locally (For Testing)

Keep your backend running on your machine while hosting the frontend on Azure.

```powershell
cd c:\mygit\CriticalPath-AI-E2
.\scripts\run-local.ps1
```

**What this does:**
1. Creates Python virtual environment
2. Installs dependencies
3. Prompts for API keys (Azure OpenAI or OpenAI)
4. Starts Azure Functions emulator on **`http://localhost:7071`**

**Terminal output example:**
```
================================================
Starting CriticalPath AI - Local Development
================================================
Frontend: http://localhost:8080
Backend API: http://localhost:7071/api
Press Ctrl+C to stop
```

### Test Endpoints Locally
```powershell
# Test projects endpoint
curl http://localhost:7071/api/projects

# Test session creation
curl -X POST http://localhost:7071/api/session `
  -Headers @{"Content-Type"="application/json"} `
  -Body '{"proj_id":"P01-1"}'
```

---

## 🌐 Step 3: Deploy Frontend to Azure Static Web Apps

### Option A: Automatic Deployment via GitHub

1. **Push code to GitHub:**
   ```powershell
   cd c:\mygit\CriticalPath-AI-E2
   git add .
   git commit -m "Deploy to Azure"
   git push origin main
   ```

2. **Azure will automatically:**
   - Detect the push
   - Build the app (GitHub Actions workflow)
   - Deploy to Static Web App
   - Get a public URL (e.g., `https://cp-app-swa.azurestaticapps.net`)

3. **Verify deployment:**
   - Check GitHub Actions: https://github.com/YOUR-USERNAME/CriticalPath-AI-E2/actions
   - Wait for workflow to complete
   - Visit the Static Web App URL

### Option B: Manual Deployment via CLI

```powershell
cd c:\mygit\CriticalPath-AI-E2

# Deploy all frontend files
swa deploy .\frontend `
  --env production `
  --deployment-token <your-swa-deployment-token>
```

---

## 📊 Step 4: Configure API Routing

Your frontend needs to know where the backend is.

### For Local Testing:
- Frontend auto-detects `localhost` and routes to `http://localhost:7071`
- No changes needed!

### For Azure Production:
The `staticwebapp.config.json` file handles routing:
```json
{
  "routes": [
    {
      "route": "/api/*",
      "allowedRoles": ["anonymous"]
    }
  ]
}
```

This configuration proxies `/api/*` calls through Azure Static Web Apps.

---

## 🔧 Step 5: Upload CSV Data to Blob Storage

The deployment script uploads CSV files automatically, but you can add more data later:

```powershell
$storageAccount = "cpapistg"  # Your storage account name
$container = "project-data"
$storageKey = "your-storage-key"

# Upload new CSV files
Get-ChildItem "data/*.csv" | ForEach-Object {
    az storage blob upload `
        --account-name $storageAccount `
        --account-key $storageKey `
        --container-name $container `
        --name $_.Name `
        --file $_.FullName
}
```

---

## 💡 Architecture Diagram

### Local Testing Setup
```
Your Machine                          Azure Cloud
┌──────────────────────────┐         ┌────────────────────────┐
│ Frontend                 │         │ Azure OpenAI Service   │
│ (http://localhost:8080)  │────────►│ (API calls)            │
│                          │         │                        │
│ Backend Functions Emulator         │ Azure Blob Storage     │
│ (http://localhost:7071)  │────────►│ (CSV data)             │
└──────────────────────────┘         └────────────────────────┘
```

### Production Setup
```
Browser                              Azure Cloud
   │                    ┌─────────────────────────────────────┐
   │                    │ Static Web Apps (Frontend)          │
   ├───────────────────►│ https://cp-app-swa.azurestaticapps │
   │                    │                                     │
   │                    │ /api/* → localhost:7071 (your PC)   │
   │                    └─────────────────────────────────────┘
   │                                    │
   │                                    ▼
   │ Your Machine
   │ ┌────────────────────────────────────────┐
   └─►│ Functions Emulator (Backend)          │
      │ http://localhost:7071                │
      │ (via any Internet connection)         │
      └────────────────────────────────────────┘
```

---

## 🧪 Testing Checklist

- [ ] Backend running locally: `http://localhost:7071/api/projects`
- [ ] Frontend loaded: Visit Static Web App URL
- [ ] Load projects: Select a project in the dropdown
- [ ] Start session: Click "Start Session"
- [ ] Send message: Type a question and send
- [ ] Check console: Open browser DevTools (F12) → Console for errors

---

## 📱 Environment Variables

### For Local Backend (set in run-local.ps1)
```
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_ENDPOINT=<your-endpoint>
AZURE_STORAGE_CONNECTION_STRING=<your-blob-connection>
OPENAI_MODEL=gpt-4o-mini
MAX_HISTORY_MESSAGES=20
```

### For Azure Function App (set during deploy-azure.ps1)
Same as above, stored in Azure Key Vault / App Settings

---

## 🔐 Security Notes

1. **Never commit secrets** - Use `.env` files (add to `.gitignore`)
2. **GitHub Tokens** - Use fine-grained tokens with limited scopes
3. **Azure Keys** - Store in Azure Key Vault, not in code
4. **CORS** - Static Web Apps automatically handle CORS for /api routes

---

## 🐛 Troubleshooting

### Issue: "Cannot GET /api/projects"
**Solution:** Backend not running. Run `.\scripts\run-local.ps1` in another terminal.

### Issue: "CORS error"
**Solution:** This shouldn't happen on Azure, but for local testing, ensure backend is running.

### Issue: "API key not found"
**Solution:** Set environment variables before starting backend:
```powershell
$env:AZURE_OPENAI_API_KEY = "your-key"
$env:AZURE_OPENAI_ENDPOINT = "your-endpoint"
```

### Issue: Functions deployment fails
**Solution:** Make sure you're in the `api` folder:
```powershell
cd api
func azure functionapp publish <function-app-name>
```

### Issue: Static Web App shows 404
**Solution:** Check GitHub Actions workflow output for build errors.

---

## 📞 Next Steps

1. **Complete Step 1**: Run `.\scripts\deploy-azure.ps1`
2. **Start Testing**: Run `.\scripts\run-local.ps1`
3. **Deploy Frontend**: Push to GitHub main branch
4. **Verify**: Visit Static Web App URL and test endpoints
5. **(Optional) Move Backend to Azure**: Run `.\scripts\deploy-functions.ps1` later

---

## 🎯 Hosting Plans Summary

| Component | Plan | Cost | Notes |
|-----------|------|------|-------|
| **Static Web Apps** | Free | $0 | 1 free app per subscription |
| **Function App** | Consumption | Pay-per-call | ~$0.20 per million executions |
| **Blob Storage** | Standard LRS | ~$0.024/GB | Low cost for small data |
| **Azure OpenAI** | Pay-per-token | Varies | ~$0.003/1K input tokens |

---

## 📖 Useful Links

- [Azure Static Web Apps Docs](https://docs.microsoft.com/en-us/azure/static-web-apps/)
- [Azure Functions Docs](https://docs.microsoft.com/en-us/azure/azure-functions/)
- [Azure CLI Reference](https://docs.microsoft.com/en-us/cli/azure/)
- [GitHub Actions Docs](https://docs.github.com/en/actions)
