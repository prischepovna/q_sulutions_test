import os


def UploadVideo(server_url: str, video_path: str, company_name: str, sidecar_path: str | None = None) -> str:
    import requests  # lazy: recorder must work without requests when --server is unused

    url = f"{server_url.rstrip('/')}/upload"

    files = {}
    with open(video_path, 'rb') as f:
        files['file'] = (os.path.basename(video_path), f)
        data = {'company_name': company_name}

        if sidecar_path and os.path.exists(sidecar_path):
            with open(sidecar_path, 'rb') as sf:
                files['sidecar'] = (os.path.basename(sidecar_path), sf)
                response = requests.post(url, files=files, data=data, timeout=(10, 300))
        else:
            response = requests.post(url, files=files, data=data, timeout=(10, 300))

    response.raise_for_status()
    res_data = response.json()
    return res_data.get('processed_video_url') or res_data['video_url']


def GetVideoURL(server_url: str, company_name: str, prefer_processed: bool = True) -> str:
    import requests

    url = f"{server_url.rstrip('/')}/get_video_url"
    response = requests.get(url, params={'company_name': company_name}, timeout=30)
    response.raise_for_status()
    data = response.json()
    if prefer_processed and data.get('processed_video_url'):
        return data['processed_video_url']
    return data['video_url']


def ProcessVideo(server_url: str, company_name: str) -> dict:
    import requests

    url = f"{server_url.rstrip('/')}/process"
    response = requests.post(url, json={'company_name': company_name}, timeout=(10, 300))
    response.raise_for_status()
    return response.json()
