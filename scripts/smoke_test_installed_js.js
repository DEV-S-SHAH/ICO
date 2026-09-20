/**
 * Post-publish fresh-install smoke test for ico-cache-js.
 */
const { IcoCache, icoCache } = require(process.env.PACKAGE_PATH || 'ico-cache-js');

console.log('==> Running ico-cache-js post-install smoke test...');

if (typeof IcoCache !== 'function') {
  console.error('SMOKE TEST FAILED: IcoCache is not a constructor/function');
  process.exit(1);
}

const client = icoCache({ baseUrl: 'http://localhost:8000' });
if (!client || typeof client.resolve !== 'function') {
  console.error('SMOKE TEST FAILED: client.resolve is not a function');
  process.exit(1);
}

console.log('✓ Successfully initialized IcoCache client.');
console.log('========================================================');
console.log('  ✓ JS FRESH-INSTALL SMOKE TEST PASSED SUCCESSFULLY');
console.log('========================================================');
