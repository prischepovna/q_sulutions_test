import os


def UploadVideo(server_url: str, video_path: str, company_name: str) -> str:
    import requests  # lazy: recorder must work without requests when --server is unused

    url = f"{server_url.rstrip('/')}/upload"

    with open(video_path, 'rb') as f:
        files = {'file': (os.path.basename(video_path), f)}
        data = {'company_name': company_name}
        response = requests.post(url, files=files, data=data, timeout=(10, 300))

    response.raise_for_status()
    return response.json()['video_url']


def GetVideoURL(server_url: str, company_name: str) -> str:
    import requests

    url = f"{server_url.rstrip('/')}/get_video_url"
    response = requests.get(url, params={'company_name': company_name}, timeout=30)
    response.raise_for_status()
    return response.json()['video_url']