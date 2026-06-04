# Deploying EPF Tracker Scraper to a DigitalOcean Droplet (Ubuntu 24.04)

This guide walks you through deploying your Python scraping script to your newly created DigitalOcean Droplet.

---

## ⚠️ Critical Note: Resource Limitations (512MB RAM)
Your Droplet (`ubuntu-s-1vcpu-512mb-10gb`) has **512MB of RAM**. Headless Chromium (run by Playwright) is memory-intensive and will likely crash with Out-Of-Memory (OOM) errors if you run it with only 512MB of RAM.

**Before doing anything else, you must set up a Swap File** on the Droplet to act as virtual memory. This is required for Chromium to run reliably.

### 1. Configure a 2GB Swap File
Run the following commands in your Droplet terminal (logged in as `root`):

```bash
# Create the swap file (2GB)
fallocate -l 2G /swapfile

# Set the correct file permissions
chmod 600 /swapfile

# Set up the swap area
mkswap /swapfile

# Enable the swap file
swapon /swapfile

# Make the swap file permanent (persists after reboot)
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# Verify swap is active
free -h
```
*You should now see `Swap: 2.0Gi` in the output of the `free -h` command.*

---

## Step 2: System Update and Package Setup

Update the system repository index and install Python environment tools:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git
```

---

## Step 3: Clone Code and Configure Environment

Navigate to the directory where you want to host the project (e.g. `/opt/epftracker` or your user home directory `/root/epftracker`):

```bash
# Create project folder and enter it
mkdir -p /root/epftracker
cd /root/epftracker

# (Alternative) If you are using Git:
# git clone <your-repo-url> /root/epftracker
# cd /root/epftracker
```

Once your project files (specifically `requirements.txt`, `vendor_scraper.py`, `STATECODE.JSON`, `districts.json`, `VENDORLIST.csv`) are placed in `/root/epftracker`:

```bash
# Create a Python Virtual Environment
python3 -m venv venv

# Automatically set the OpenRouter API Key when activating the virtual environment
echo 'export OPENROUTER_API_KEY=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'
>> venv/bin/activate

# Activate the virtual environment
source venv/bin/activate

# Install the Python dependencies (Playwright, PIL, Pandas, Openpyxl, Requests, etc.)
pip install -r requirements.txt
```


---

## Step 4: Install Playwright and Browser Dependencies

Since we only need Chromium (and not Firefox or WebKit), we can install just Chromium to save disk space on your 10GB storage limit:

```bash
# Install Chromium browser binary
playwright install chromium

# Install system dependencies (libraries needed to run Chromium on Ubuntu headless)
playwright install-deps chromium
```

---

## Step 5: Run the Scraper

To run the scraper on the server, make sure your virtual environment is active:
```bash
source venv/bin/activate
```

You can choose between **Headless** or **Virtual Non-Headless** execution styles:

### A. Headless Mode (Recommended for Server Production)
Runs the browser silently in the background. It consumes the least system resources:
```bash
python -u vendor_scraper.py --input vendorList.csv --headless
```

### B. Virtual Non-Headless Mode (Recommended if EPFO blocks headless requests)
If the portal detects and blocks headless scraping, you can run the browser in "non-headless" mode inside a virtual framebuffer. This mimics a real screen and hides headless indicators:
```bash
# 1. Install Xvfb (only needs to be run once)
sudo apt install -y xvfb

# 2. Run the script inside Xvfb (without passing the --headless flag)
xvfb-run -a python -u vendor_scraper.py --input vendorList.csv
```

---

## Step 6: Scheduling with Cron (Optional)

If you want the scraper to run automatically (e.g., every day at midnight):

1. Open the crontab editor:
   ```bash
   crontab -e
   ```
2. Add a line pointing to your virtual environment's Python binary. Choose one of the scheduling styles:

   * **For Headless execution**:
     ```text
     0 0 * * * cd /root/epftracker && /root/epftracker/venv/bin/python -u vendor_scraper.py --input vendorList.csv --headless >> /root/epftracker/cron.log 2>&1
     ```

   * **For Virtual Non-Headless execution (using xvfb)**:
     ```text
     0 0 * * * cd /root/epftracker && xvfb-run /root/epftracker/venv/bin/python -u vendor_scraper.py --input vendorList.csv >> /root/epftracker/cron.log 2>&1
     ```

---

## Step 7: GitHub Continuous Deployment (Push to Deploy)

To push changes from your local repository to your GitHub repository and have them update directly on your DigitalOcean Droplet, you have two options: a quick manual pull or a fully automated GitHub Actions pipeline.

### Option A: Manual Deployment via Git Pull (Easiest to Setup)

1. **Add SSH Key to GitHub**:
   Generate an SSH key on your Droplet if you don't have one:
   ```bash
   ssh-keygen -t ed25519 -C "droplet@epftracker"
   cat ~/.ssh/id_ed25519.pub
   ```
   Copy the output and add it to your GitHub account under **Settings > SSH and GPG keys**.

2. **Clone the Repo on the Droplet via SSH**:
   ```bash
   cd /root
   git clone git@github.com:yourusername/epftracker.git
   ```

3. **Pull Changes**:
   Whenever you push local changes to GitHub, SSH into your Droplet and run:
   ```bash
   cd /root/epftracker
   git pull origin main
   source venv/bin/activate
   pip install -r requirements.txt
   ```

---

### Option B: Automated Deployment via GitHub Actions (Recommended)

This method automatically deploys your updates onto the Droplet whenever you push a change to the `main` branch.

1. **Add SSH Key to Droplet's Authorized Keys**:
   If not already done, generate an SSH key pair locally on your computer, add the public key to `/root/.ssh/authorized_keys` on your Droplet, and keep the private key.

2. **Configure GitHub Repository Secrets**:
   In your GitHub repository, go to **Settings > Secrets and variables > Actions** and create the following secrets:
   - `DROPLET_HOST`: The public IP of your droplet (`139.59.22.59`).
   - `DROPLET_USERNAME`: `root`.
   - `DROPLET_SSH_KEY`: The private SSH key (usually matches the public key in your Droplet's `authorized_keys`).

3. **Create the GitHub Actions Workflow File**:
   In your local repository, create a directory structure `.github/workflows/` and a file named `deploy.yml`:

```yaml
name: Deploy Scraper to DigitalOcean

on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.DROPLET_HOST }}
          username: ${{ secrets.DROPLET_USERNAME }}
          key: ${{ secrets.DROPLET_SSH_KEY }}
          port: 22
          script: |
            cd /root/epftracker
            git pull origin main
            source venv/bin/activate
            pip install -r requirements.txt
```
*Whenever you push code to GitHub now, GitHub will automatically log into the Droplet, pull the code, and update Python packages.*
