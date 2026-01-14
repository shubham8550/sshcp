#!/usr/bin/env node

const { spawn, spawnSync } = require('child_process');
const path = require('path');

const PACKAGE_NAME = 'sshcp';

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

/**
 * Run sshcp using the best available method
 */
function runSshcp(args) {
  // Try uvx first (fastest, from uv package manager)
  if (commandExists('uvx')) {
    const proc = spawn('uvx', [PACKAGE_NAME, ...args], {
      stdio: 'inherit',
    });
    proc.on('close', (code) => process.exit(code || 0));
    return;
  }

  // Try pipx (common Python tool runner)
  if (commandExists('pipx')) {
    const proc = spawn('pipx', ['run', PACKAGE_NAME, ...args], {
      stdio: 'inherit',
    });
    proc.on('close', (code) => process.exit(code || 0));
    return;
  }

  // Try direct sshcp command (if installed via pip)
  if (commandExists('sshcp')) {
    const proc = spawn('sshcp', args, {
      stdio: 'inherit',
    });
    proc.on('close', (code) => process.exit(code || 0));
    return;
  }

  // No method available - show installation instructions
  console.error(`
╭─────────────────────────────────────────────────────────────────╮
│  sshcp requires Python and one of: uv, pipx, or pip            │
╰─────────────────────────────────────────────────────────────────╯

Install using one of these methods:

  1. Using uv (recommended - fastest):
     curl -LsSf https://astral.sh/uv/install.sh | sh
     uvx sshcp --help

  2. Using pipx:
     pip install pipx
     pipx run sshcp --help

  3. Using pip:
     pip install sshcp
     sshcp --help

Learn more: https://github.com/shubham8550/sshcp
`);
  process.exit(1);
}

// Get command line arguments (skip node and script path)
const args = process.argv.slice(2);

// Run sshcp with arguments
runSshcp(args);

