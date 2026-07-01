/* VisualLM — minimal ZIP reader/writer (STORE, no compression).
 *
 * Dependency-free so it works under the browser edition's strict CSP (no CDN
 * libraries). STORE-only zips are uncompressed but are valid, standard zips that
 * Finder / Explorer / `unzip` / Python `zipfile` all open. Used to package a DLC
 * as a browsable folder (manifest.json + demos/*.json + experiments/*.json).
 *
 * VisualLMZip.zip(files)  — files: [{name, text}] -> Uint8Array (a .zip)
 * VisualLMZip.unzip(buf)  — Uint8Array|ArrayBuffer -> [{name, text}]
 */
(function (global) {
  "use strict";

  const CRC_TABLE = (function () {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();

  function crc32(bytes) {
    let c = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }

  const enc = new TextEncoder();
  const dec = new TextDecoder();

  function zip(files) {
    const chunks = [];
    const central = [];
    let offset = 0;
    for (const f of files) {
      const nameBytes = enc.encode(f.name);
      const data = enc.encode(f.text != null ? f.text : "");
      const crc = crc32(data);

      const lfh = new DataView(new ArrayBuffer(30));
      lfh.setUint32(0, 0x04034b50, true); // local file header signature
      lfh.setUint16(4, 20, true); // version needed
      lfh.setUint16(6, 0x0800, true); // flags: bit 11 = UTF-8 names
      lfh.setUint16(8, 0, true); // method: 0 = store
      lfh.setUint16(10, 0, true); // mod time
      lfh.setUint16(12, 0x21, true); // mod date (1980-01-01, minimal valid)
      lfh.setUint32(14, crc, true);
      lfh.setUint32(18, data.length, true); // compressed size
      lfh.setUint32(22, data.length, true); // uncompressed size
      lfh.setUint16(26, nameBytes.length, true);
      lfh.setUint16(28, 0, true); // extra length
      const lfhBytes = new Uint8Array(lfh.buffer);
      chunks.push(lfhBytes, nameBytes, data);

      const cd = new DataView(new ArrayBuffer(46));
      cd.setUint32(0, 0x02014b50, true); // central dir header signature
      cd.setUint16(4, 20, true); // version made by
      cd.setUint16(6, 20, true); // version needed
      cd.setUint16(8, 0x0800, true); // flags UTF-8
      cd.setUint16(10, 0, true); // method
      cd.setUint16(12, 0, true); // time
      cd.setUint16(14, 0x21, true); // date
      cd.setUint32(16, crc, true);
      cd.setUint32(20, data.length, true);
      cd.setUint32(24, data.length, true);
      cd.setUint16(28, nameBytes.length, true);
      cd.setUint16(30, 0, true); // extra
      cd.setUint16(32, 0, true); // comment
      cd.setUint16(34, 0, true); // disk number
      cd.setUint16(36, 0, true); // internal attrs
      cd.setUint32(38, 0, true); // external attrs
      cd.setUint32(42, offset, true); // local header offset
      central.push(new Uint8Array(cd.buffer), nameBytes);

      offset += lfhBytes.length + nameBytes.length + data.length;
    }

    const cdStart = offset;
    let cdSize = 0;
    for (const p of central) cdSize += p.length;

    const eocd = new DataView(new ArrayBuffer(22));
    eocd.setUint32(0, 0x06054b50, true); // end of central dir signature
    eocd.setUint16(4, 0, true); // disk number
    eocd.setUint16(6, 0, true); // cd start disk
    eocd.setUint16(8, files.length, true); // entries this disk
    eocd.setUint16(10, files.length, true); // total entries
    eocd.setUint32(12, cdSize, true);
    eocd.setUint32(16, cdStart, true);
    eocd.setUint16(20, 0, true); // comment length

    const all = chunks.concat(central, [new Uint8Array(eocd.buffer)]);
    let total = 0;
    for (const p of all) total += p.length;
    const out = new Uint8Array(total);
    let pos = 0;
    for (const p of all) {
      out.set(p, pos);
      pos += p.length;
    }
    return out;
  }

  function unzip(buf) {
    const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let eocd = -1;
    for (let i = bytes.length - 22; i >= 0; i--) {
      if (dv.getUint32(i, true) === 0x06054b50) {
        eocd = i;
        break;
      }
    }
    if (eocd < 0) throw new Error("Not a valid .zip (missing end-of-central-directory).");
    const count = dv.getUint16(eocd + 10, true);
    let p = dv.getUint32(eocd + 16, true);
    const out = [];
    for (let n = 0; n < count; n++) {
      if (dv.getUint32(p, true) !== 0x02014b50) throw new Error("Corrupt .zip (bad central directory).");
      const compSize = dv.getUint32(p + 20, true);
      const nameLen = dv.getUint16(p + 28, true);
      const extraLen = dv.getUint16(p + 30, true);
      const commentLen = dv.getUint16(p + 32, true);
      const lfhOff = dv.getUint32(p + 42, true);
      const name = dec.decode(bytes.subarray(p + 46, p + 46 + nameLen));
      const lfhNameLen = dv.getUint16(lfhOff + 26, true);
      const lfhExtraLen = dv.getUint16(lfhOff + 28, true);
      const dataStart = lfhOff + 30 + lfhNameLen + lfhExtraLen;
      const data = bytes.subarray(dataStart, dataStart + compSize);
      // Skip directory entries (name ends with "/").
      if (!name.endsWith("/")) out.push({ name: name, text: dec.decode(data) });
      p += 46 + nameLen + extraLen + commentLen;
    }
    return out;
  }

  global.VisualLMZip = { zip: zip, unzip: unzip, crc32: crc32 };
})(typeof window !== "undefined" ? window : this);
