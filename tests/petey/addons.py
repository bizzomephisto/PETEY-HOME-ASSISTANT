"""Host manifest contract used by the public add-on tests."""


class AddonManager:
    @staticmethod
    def _validate_manifest(manifest, folder):
        if manifest.get("api_version") != 1:
            raise ValueError("Unsupported add-on API version")
        if not manifest.get("id") or not manifest.get("entrypoint"):
            raise ValueError("Invalid add-on manifest")
        return {**manifest, "folder": folder}
