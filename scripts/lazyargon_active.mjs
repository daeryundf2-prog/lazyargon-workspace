// lazyargon_active.mjs — is the sibling lazyargon plugin installed AND enabled?
// Installed = <plugins>/lazyargon/<marker> exists. Enabled = Antigravity config.json does not set
// plugins.lazyargon.enabled to false. An unreadable/missing config keeps the old file-only answer.
// Config path: $LAZYARGON_GEMINI_CONFIG, else <plugins>/../config.json (~/.gemini/config/config.json).
import fs from 'node:fs';
import path from 'node:path';

export function lazyargonActive(pluginRoot, marker = 'plugin.json', env = process.env) {
	const pluginsDir = path.resolve(pluginRoot, '..');
	if (!fs.existsSync(path.join(pluginsDir, 'lazyargon', marker))) return false;
	const configPath = env.LAZYARGON_GEMINI_CONFIG || path.join(pluginsDir, '..', 'config.json');
	try {
		const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
		return config?.plugins?.lazyargon?.enabled !== false;
	} catch {
		return true;
	}
}
