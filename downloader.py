# Downloads the `vanilla-mcdoc/java` folder for use with `compiler.py`
import os
import requests
from urllib.parse import urljoin

# Settings
GITHUB_API = "https://api.github.com"
REPO_OWNER = "SpyglassMC"
REPO_NAME = "vanilla-mcdoc"
BRANCH_FOLDER = "main"
BRANCH_FILE = "locales"
FOLDER_PATH = "java"

DOWNLOAD_DIR = "."

HEADERS = {
    "Accept": "application/vnd.github.v3+json",
}


def download_file_from_repo(branch, path, local_dir):
    """Download a single file from the GitHub repository."""
    raw_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{branch}/{path}"
    local_path = os.path.join(local_dir, os.path.basename(path))
    os.makedirs(local_dir, exist_ok=True)

    response = requests.get(raw_url, headers=HEADERS)
    if response.status_code == 200:
        with open(local_path, "wb") as f:
            f.write(response.content)
        print(f"Downloaded: {path}")
    else:
        print(f"Failed to download {path} (status {response.status_code})")


def download_folder_from_repo(folder_path, branch, local_dir):
    """Download all files in a folder from the GitHub repository using the API."""
    url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/contents/{folder_path}?ref={branch}"
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        print(f"Failed to list contents of folder {folder_path} (status {response.status_code})")
        return

    items = response.json()
    for item in items:
        if item["type"] == "file":
            download_file_from_repo(branch, item["path"], os.path.join(local_dir, folder_path))
        elif item["type"] == "dir":
            download_folder_from_repo(item["path"], branch, local_dir)


def main():
    print("Downloading folder...")
    download_folder_from_repo(FOLDER_PATH, BRANCH_FOLDER, DOWNLOAD_DIR)


if __name__ == "__main__":
    main()
