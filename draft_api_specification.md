# REST API Specification

## Endpoints Overview

| Method | Endpoint | Description | Status Code | Notes / Returns |
| :--- | :--- | :--- | :--- | :--- |
| **GET** | `/health` | Basic hardware check. | 200 | Reports if HW is connected/functional. |
| **GET** | `/status` | Backend service status. | 200 | Returns `ready`, `busy`, or `error`. |
| **GET** | `/jobs` | List all known jobs. | 200 | Returns array of all job objects. |
| **GET** | `/jobs/<ID>` | Retrieve specific job data. | 200/404 | Returns full job object for `<ID>`. |
| **GET** | `/jobs/latest` | Retrieve latest job data. | 200/404 | Returns most recent job object. |
| **GET** | `/profiles` | List configuration profiles. | 200 | Returns array of available profiles. |
| **GET** | `/profiles/default` | Get default profile. | 200 | Returns the default configuration profile. |
| **POST** | `/jobs` | Initiate a new job. | 201 | **Body:** `options`, `path`<br>**Returns:** Full job object with `ID`. |
| **POST** | `/streams/camera` | Start camera stream. | 201 | Starts the raw video feed. |
| **POST** | `/streams/detection`| Start detection stream. | 201 | Starts the processed detection feed. |
| **POST** | `/paths` | Generate a path. | 201 | **Body:** `options`<br>**Returns:** Path object based on options. |
| **DELETE** | `/streams/camera` | Stop camera stream. | 204 | |
| **DELETE** | `/streams/detection`| Stop detection stream. | 204 | |
| **DELETE** | `/jobs/<jobID>` | Stop job. | 204 | Stops and removes job for `<jobID>`. |

---

## Data Models

### Job Object
The job object encapsulates the configuration, output data, and current processing state.

```json
{
  "options": "string/object",
  "path": "string",
  "log": "string",
  "measurements": [],
  "path-image": "string (url/base64)",
  "status": {
    "lastPointProcessed": "integer",
    "error": "string/null"
  }
}
```
