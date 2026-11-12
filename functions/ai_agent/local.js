'use strict';
/**
 * Plain local runner (no Catalyst login needed): mounts the function at the same path
 * Catalyst uses (/server/ai_agent) and serves the web client, using memory storage.
 *   npm run local   ->  http://localhost:3000
 * For the real Catalyst emulator (Data Store/Cache), use `catalyst serve` from the project root.
 */
process.env.LOCAL_MODE = process.env.LOCAL_MODE || '1';
const path = require('path');
const express = require('express');
const fn = require('./index');

const server = express();
server.use('/server/ai_agent', fn);
server.use(express.static(path.join(__dirname, '..', '..', 'client')));

const port = Number(process.env.PORT) || 3000;
server.listen(port, () => console.log(`AI agent running at http://localhost:${port} (provider: ${process.env.LLM_PROVIDER || 'mock'})`));
