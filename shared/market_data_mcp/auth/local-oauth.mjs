// OAuth cache compatibility is isolated here; the query path never launches a browser.
import { createHash, randomUUID } from 'node:crypto';
import { readFile, mkdir, writeFile, rename, rm } from 'node:fs/promises';
import path from 'node:path';
import { PortalError } from '../core/errors.mjs';

export class LocalOAuthProvider {
  constructor(directory, serverUrl) {
    const hash = createHash('md5').update(serverUrl).digest('hex'); // mcp-remote v1 cache key, not a security primitive
    this.directory = path.join(directory, 'mcp-remote-v1');
    this.prefix = path.join(this.directory, hash);
  }
  get redirectUrl() { return 'http://127.0.0.1:18273/oauth/callback'; }
  get clientMetadata() {
    return { client_name: 'Market data query portal', redirect_uris: [this.redirectUrl],
      grant_types: ['authorization_code', 'refresh_token'], response_types: ['code'], token_endpoint_auth_method: 'none' };
  }
  async read(suffix) {
    try { return JSON.parse(await readFile(`${this.prefix}_${suffix}.json`, 'utf8')); }
    catch (error) {
      if (error.code === 'ENOENT') return undefined;
      throw new PortalError('auth_required');
    }
  }
  clientInformation() { return this.read('client_info'); }
  tokens() { return this.read('tokens'); }
  async saveTokens(tokens) {
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    const temporary = `${this.prefix}_${randomUUID()}.tmp`;
    try {
      await writeFile(temporary, JSON.stringify({ ...tokens,
        expires_at: tokens.expires_in ? Date.now() + tokens.expires_in * 1000 : undefined }),
      { mode: 0o600, flag: 'wx' });
      await rename(temporary, `${this.prefix}_tokens.json`);
    } finally { await rm(temporary, { force: true }); }
  }
  // Registration, PKCE and browser interaction are explicit manage.py auth operations.
  redirectToAuthorization() { throw new PortalError('auth_required'); }
  saveCodeVerifier() { throw new PortalError('auth_required'); }
  codeVerifier() { throw new PortalError('auth_required'); }
}
