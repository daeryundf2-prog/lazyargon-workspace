// lazyargon_active.mjs — is a sibling LazyArgon-family plugin (lazyargon or its Neon fork lazyneon) installed AND enabled?
// Installed = <plugins>/<name>/<marker> exists. Enabled = Antigravity config.json does not set
// plugins.<name>.enabled to false. An unreadable/missing config keeps the old file-only answer.
// Config path: $LAZYARGON_GEMINI_CONFIG, else <plugins>/../config.json (~/.gemini/config/config.json).
import fs from 'node:fs';
import path from 'node:path';

const FAMILY = ['lazyargon', 'lazyneon'];

export function lazyargonActive(pluginRoot, marker = 'plugin.json', env = process.env) {
	const pluginsDir = path.resolve(pluginRoot, '..');
	const installed = FAMILY.filter((name) => fs.existsSync(path.join(pluginsDir, name, marker)));
	if (installed.length === 0) return false;
	const configPath = env.LAZYARGON_GEMINI_CONFIG || path.join(pluginsDir, '..', 'config.json');
	let config;
	try {
		config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
	} catch {
		return true;
	}
	return installed.some((name) => config?.plugins?.[name]?.enabled !== false);
}
