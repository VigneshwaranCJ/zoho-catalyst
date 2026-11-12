'use strict';
/**
 * Storage layer showing two Catalyst features:
 *  - Data Store (table "AgentNotes") for long-term notes the agent saves
 *  - Cache (default segment) for short-term conversation history
 * When the Catalyst SDK is not available (plain local run), falls back to memory.
 */

const NOTES_TABLE = 'AgentNotes';
const HISTORY_TTL_HOURS = 2;

const memory = { notes: [], history: new Map() };

function createStorage(catalystApp) {
  if (!catalystApp) return memoryStorage();

  return {
    kind: 'catalyst',

    async saveNote(text) {
      const row = await catalystApp.datastore().table(NOTES_TABLE).insertRow({ note: text });
      return { id: row.ROWID, note: row.note };
    },

    async listNotes(limit = 20) {
      const q = `SELECT ROWID, note, CREATEDTIME FROM ${NOTES_TABLE} ORDER BY CREATEDTIME DESC LIMIT ${Number(limit) || 20}`;
      const rows = await catalystApp.zcql().executeZCQLQuery(q);
      return rows.map((r) => ({ id: r[NOTES_TABLE].ROWID, note: r[NOTES_TABLE].note, created: r[NOTES_TABLE].CREATEDTIME }));
    },

    async getHistory(sessionId) {
      try {
        const value = await catalystApp.cache().segment().getValue(historyKey(sessionId));
        return value ? JSON.parse(value) : [];
      } catch {
        return [];
      }
    },

    async saveHistory(sessionId, history) {
      // Cache values are size-limited, keep only the last few turns.
      const trimmed = JSON.stringify(history.slice(-12));
      try {
        await catalystApp.cache().segment().put(historyKey(sessionId), trimmed, HISTORY_TTL_HOURS);
      } catch (err) {
        console.warn('Cache write failed:', err.message);
      }
    },
  };
}

function memoryStorage() {
  return {
    kind: 'memory',
    async saveNote(text) {
      const note = { id: String(Date.now()), note: text, created: new Date().toISOString() };
      memory.notes.unshift(note);
      return note;
    },
    async listNotes(limit = 20) {
      return memory.notes.slice(0, limit);
    },
    async getHistory(sessionId) {
      return memory.history.get(sessionId) || [];
    },
    async saveHistory(sessionId, history) {
      memory.history.set(sessionId, history.slice(-12));
    },
  };
}

function historyKey(sessionId) {
  return `hist_${String(sessionId).replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 40)}`;
}

module.exports = { createStorage };
