#!/usr/bin/env node

const { spawnSync } = require('child_process');

/**
 * Check if a command exists
 */
function commandExists(cmd) {
  try {
    const result = spawnSync(process.platform === 'win32' ? 'where' : 'which', [cmd], {
      stdio: 'pipe',
    });
    return result.status === 0;
  } catch {
    return false;
  }
}

// Check for available Python runners
const hasUvx = commandExists('uvx');
const hasPipx = commandExists('pipx');
const hasSshcp = commandExists('sshcp');

if (hasUvx || hasPipx || hasSshcp) {
  // At least one method available
  if (hasUvx) {
    console.log('✓ sshcp will use uvx (fastest)');
  } else if (hasPipx) {
    console.log('✓ sshcp will use pipx');
  } else {
    console.log('✓ sshcp found in PATH');
  }
} else {
  console.warn(`
⚠ sshcp requires Python and a package runner

For best experience, install uv:
  curl -LsSf https://astral.sh/uv/install.sh | sh

Or install pipx:
  pip install pipx

Then run: npx sshcp --help
`);
}

