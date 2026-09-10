/**
 * Запуск всех тестов: node tests/frontend/run-all.mjs
 *
 * Каждый файл запускается отдельным процессом (тесты подменяют глобальные
 * объекты — document, localStorage, fetch — и не должны мешать друг другу).
 * Штатный `node --test` здесь не используется: подмена глобального Event ломает
 * его протокол обмена с дочерним процессом.
 *
 * Код возврата 0 — ни одна поломка не воспроизвелась, 1 — есть падения.
 */
import { readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const dir = path.dirname(fileURLToPath(import.meta.url));
const files = readdirSync(dir).filter((name) => name.endsWith('.test.mjs')).sort();

let failed = 0;
const summary = [];

for (const file of files) {
  console.log(`\n${'='.repeat(72)}\n${file}\n${'='.repeat(72)}`);
  const result = spawnSync(process.execPath, [path.join(dir, file)], {
    stdio: 'inherit',
    env: { ...process.env, NODE_OPTIONS: '' },
  });
  if (result.status !== 0) {
    failed += 1;
    summary.push(`ПАДАЕТ  ${file}`);
  } else {
    summary.push(`проходит ${file}`);
  }
}

console.log(`\n${'='.repeat(72)}\nИТОГ\n${'='.repeat(72)}`);
summary.forEach((line) => console.log(' ', line));
console.log(`\nфайлов с падениями: ${failed} из ${files.length}`);
process.exit(failed ? 1 : 0);
