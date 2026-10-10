// Deployment setting, loaded before the app. Leave empty when the page and the API share one origin
// (the Python server, or Vercel with the /api rewrite in vercel.json). Set it to the API's https URL, for example
//   window.FD_API_BASE = 'https://203-0-113-10.nip.io';
// to call the backend directly from another origin (the backend then needs FLOOD_CORS_ORIGINS=<this site>).
window.FD_API_BASE = window.FD_API_BASE || '';
