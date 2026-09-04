/**
 * Artisan Trust-Link Gateway Frontend Client
 */

document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initForms();
  loadLedgerBlocks();
});

// ---------------------------------------------------------
// Tab Navigation
// ---------------------------------------------------------
function initTabs() {
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabContents = document.querySelectorAll('.tab-content');

  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const targetTab = btn.getAttribute('data-tab');

      tabBtns.forEach(b => b.classList.remove('active'));
      tabContents.forEach(c => c.classList.remove('active'));

      btn.classList.add('active');
      const targetContent = document.getElementById(`tab-${targetTab}`);
      if (targetContent) targetContent.classList.add('active');

      if (targetTab === 'explorer') {
        loadLedgerBlocks();
      }
    });
  });
}

// ---------------------------------------------------------
// Forms Handling
// ---------------------------------------------------------
function initForms() {
  const signForm = document.getElementById('sign-form');
  const verifyForm = document.getElementById('verify-form');

  if (signForm) {
    signForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('btn-sign-submit');
      setLoading(btn, true);

      const payload = {
        broker_id: document.getElementById('broker_id').value,
        merchant_phone: document.getElementById('merchant_phone').value,
        wa_id: document.getElementById('wa_id').value,
        inquiry_text: document.getElementById('inquiry_text').value
      };

      try {
        const response = await fetch('/v1/referral/sign', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        if (!response.ok) {
          const err = await response.json();
          alert(`Error signing referral: ${err.detail || 'Request failed'}`);
          return;
        }

        const data = await response.json();
        displaySignResult(data);

        // Pre-fill verify form for convenience
        document.getElementById('v_token').value = data.signed_token;
        document.getElementById('v_wa_id').value = payload.wa_id;
        document.getElementById('v_inquiry').value = payload.inquiry_text;

        loadLedgerBlocks();
      } catch (err) {
        alert(`Network Error: ${err.message}`);
      } finally {
        setLoading(btn, false);
      }
    });
  }

  if (verifyForm) {
    verifyForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('btn-verify-submit');
      setLoading(btn, true);

      const payload = {
        token: document.getElementById('v_token').value,
        wa_id: document.getElementById('v_wa_id').value,
        inquiry_text: document.getElementById('v_inquiry').value
      };

      try {
        const response = await fetch('/v1/referral/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        if (!response.ok) {
          const err = await response.json();
          alert(`Verification Failed: ${err.detail || 'Cryptographic match failed'}`);
          return;
        }

        const data = await response.json();
        displayVerifyResult(data);
        loadLedgerBlocks();
      } catch (err) {
        alert(`Network Error: ${err.message}`);
      } finally {
        setLoading(btn, false);
      }
    });
  }
}

function setLoading(btn, isLoading) {
  const spinner = btn.querySelector('.spinner');
  const text = btn.querySelector('.btn-text');
  if (isLoading) {
    if (spinner) spinner.classList.remove('hidden');
    if (text) text.style.opacity = '0.6';
    btn.disabled = true;
  } else {
    if (spinner) spinner.classList.add('hidden');
    if (text) text.style.opacity = '1';
    btn.disabled = false;
  }
}

function displaySignResult(data) {
  const card = document.getElementById('sign-result-card');
  document.getElementById('res-signed-token').textContent = data.signed_token;
  document.getElementById('res-block-id').textContent = data.merkle_block.id;
  document.getElementById('res-parent-hash').textContent = data.merkle_block.parent_hash ? truncateHash(data.merkle_block.parent_hash) : 'GENESIS (null)';
  document.getElementById('res-current-hash').textContent = truncateHash(data.merkle_block.current_hash);

  const waLink = document.getElementById('res-wa-link');
  waLink.href = data.redirect_url;

  card.classList.remove('hidden');
}

function displayVerifyResult(data) {
  const card = document.getElementById('verify-result-card');
  document.getElementById('v-res-block-id').textContent = data.merkle_block.id;
  document.getElementById('v-res-parent-hash').textContent = data.merkle_block.parent_hash ? truncateHash(data.merkle_block.parent_hash) : 'GENESIS';
  document.getElementById('v-res-current-hash').textContent = truncateHash(data.merkle_block.current_hash);
  document.getElementById('v-res-timestamp').textContent = data.merkle_block.timestamp;

  card.classList.remove('hidden');
}

// ---------------------------------------------------------
// Ledger Explorer
// ---------------------------------------------------------
async function loadLedgerBlocks() {
  const timeline = document.getElementById('ledger-timeline');
  const totalCountLabel = document.getElementById('total-blocks-count');

  try {
    const res = await fetch('/v1/ledger/blocks');
    if (!res.ok) return;

    const blocks = await res.json();
    totalCountLabel.textContent = `${blocks.length} Block${blocks.length === 1 ? '' : 's'}`;

    if (blocks.length === 0) {
      timeline.innerHTML = '<div class="loading-state">The Merkle Ledger is currently empty. Issue a referral to create Genesis Block.</div>';
      return;
    }

    timeline.innerHTML = '';
    blocks.forEach(block => {
      const card = document.createElement('div');
      card.className = 'merkle-block-card';

      const eventType = block.payload?.event || 'BLOCK';
      const statusTag = block.payload?.status ? `<span class="badge ${block.payload.status === 'SETTLED' ? 'badge-settled' : 'badge-success'}">${block.payload.status}</span>` : '';

      card.innerHTML = `
        <div class="block-top-bar">
          <div>
            <span class="block-id-tag">Block #${block.id}</span>
            <span style="margin-left: 0.5rem; font-weight:600; font-size:0.85rem; color:#f3f4f6;">${eventType}</span>
            ${statusTag}
          </div>
          <span class="block-timestamp">${formatTime(block.timestamp)}</span>
        </div>

        <div class="hash-chain-box">
          <div class="hash-item">
            <label>Parent Hash (Anchor)</label>
            <span>${block.parent_hash ? truncateHash(block.parent_hash) : '0000000000000000 (GENESIS)'}</span>
          </div>
          <div class="hash-item">
            <label>Current Block Hash (SHA-256)</label>
            <span>${truncateHash(block.current_hash)}</span>
          </div>
        </div>

        <div class="payload-json-box">
          <code>${JSON.stringify(block.payload)}</code>
        </div>
      `;
      timeline.appendChild(card);
    });
  } catch (err) {
    console.error('Error loading blocks:', err);
  }
}

// ---------------------------------------------------------
// Ledger Auditor
// ---------------------------------------------------------
async function runLedgerAudit() {
  const btn = document.getElementById('btn-run-audit');
  setLoading(btn, true);

  const summaryCard = document.getElementById('audit-summary-card');
  const title = document.getElementById('audit-title');
  const subtitle = document.getElementById('audit-subtitle');
  const terminal = document.getElementById('audit-terminal');

  summaryCard.classList.remove('hidden');
  terminal.innerHTML = '<div class="audit-line info">Connecting to PostgreSQL Plumbline Auditor...</div>';

  try {
    const res = await fetch('/v1/ledger/audit');
    const data = await res.json();

    terminal.innerHTML = '';
    
    if (data.total_blocks === 0) {
      title.textContent = 'Ledger Empty';
      subtitle.textContent = 'No blocks to verify.';
      terminal.innerHTML = '<div class="audit-line info">[INFO] Ledger is empty. No entries to verify.</div>';
      return;
    }

    terminal.innerHTML += `<div class="audit-line info">====================== AUDITING MERKLE PLUMBLINE (${data.total_blocks} BLOCKS) ======================</div>`;

    data.details.forEach(item => {
      if (item.valid) {
        terminal.innerHTML += `<div class="audit-line ok">[OK] Block #${item.id} | Parent: ${item.parent_hash ? item.parent_hash.substring(0, 8) + '...' : 'GENESIS'} | Hash: ${item.current_hash.substring(0, 16)}...</div>`;
      } else {
        terminal.innerHTML += `<div class="audit-line fail">[FAIL] Block #${item.id} Discontinuity: ${item.error}</div>`;
      }
    });

    if (data.is_valid) {
      title.textContent = 'Plumbline True ✓';
      subtitle.textContent = `All ${data.total_blocks} block(s) verified cryptographically.`;
      terminal.innerHTML += `<div class="audit-line ok">\n[SUCCESS] The Plumbline is true. All blocks verified cryptographically.</div>`;
    } else {
      title.textContent = 'Ledger Discontinuity Detected ⚠️';
      subtitle.textContent = 'Cryptographic verification failed!';
      terminal.innerHTML += `<div class="audit-line fail">\n[FAIL] Chain tampering or parent reference corruption detected!</div>`;
    }
  } catch (err) {
    terminal.innerHTML += `<div class="audit-line fail">Error executing audit: ${err.message}</div>`;
  } finally {
    setLoading(btn, false);
  }
}

// ---------------------------------------------------------
// Helpers
// ---------------------------------------------------------
function truncateHash(hash) {
  if (!hash) return '--';
  return hash.length > 20 ? `${hash.substring(0, 10)}...${hash.substring(hash.length - 8)}` : hash;
}

function formatTime(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function copyText(elementId) {
  const text = document.getElementById(elementId).textContent;
  navigator.clipboard.writeText(text);
  alert('Copied to clipboard!');
}
