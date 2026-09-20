(() => {
  const id = name => document.getElementById(`home-assistant-${name}`);
  const base = '/api/addons/home-assistant';
  let entityRows = [];

  async function api(path, options = {}) {
    const response = await fetch(base + path, options);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Home Assistant request failed.');
    return payload;
  }

  function setStatus(message, type = '') {
    id('status').textContent = message;
    id('status').dataset.type = type;
  }

  function render(state) {
    id('url').value = state.base_url;
    id('badge').textContent = state.connected ? 'Connected' : state.has_token ? 'Ready' : 'Token needed';
    id('trusted').checked = state.trusted;
    id('review-note').textContent = state.trusted
      ? 'Trust PETEY is on. Requested Assist actions run immediately.'
      : 'Device changes wait here for approval and expire after ten minutes.';
    id('detail').textContent = state.connected
      ? `${state.tool_count} approved tools · ${state.action_count} actions · ${state.vocabulary_count || 0} customized entities · ${state.endpoint}`
      : `Endpoint: ${state.endpoint}`;
    if (!state.has_token) {
      setStatus('Paste a long-lived access token above, then choose Save & connect.', 'error');
    } else if (state.error) {
      setStatus(state.error, 'error');
    } else if (state.connected && !state.action_count) {
      setStatus('Connected for state reads only. If you want device control, remove and add Home Assistant\'s Model Context Protocol Server integration again, then choose Control Home Assistant during setup.', 'error');
    } else if (state.connected) {
      setStatus('Connected to Home Assistant MCP.', 'success');
    } else {
      setStatus('Token saved. Choose Reconnect to open the MCP connection.');
    }

    const proposals = id('proposals');
    proposals.replaceChildren();
    if (!state.proposals.length) {
      const empty = document.createElement('p');
      empty.className = 'muted';
      empty.textContent = 'No actions awaiting review.';
      proposals.append(empty);
      return;
    }
    for (const proposal of state.proposals) {
      const card = document.createElement('article');
      card.className = 'home-assistant-proposal';
      const heading = document.createElement('strong');
      heading.textContent = proposal.summary;
      const details = document.createElement('pre');
      details.textContent = JSON.stringify(proposal.arguments, null, 2);
      const actions = document.createElement('div');
      actions.className = 'inline-actions';
      for (const approve of [true, false]) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = approve ? 'primary-button' : 'secondary-button';
        button.textContent = approve ? 'Approve action' : 'Reject';
        button.addEventListener('click', () => run(button, async () => {
          const result = await api('/review', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: proposal.id, approve}),
          });
          id('result').hidden = false;
          id('result').textContent = approve ? JSON.stringify(result, null, 2) : 'Action rejected.';
        }));
        actions.append(button);
      }
      card.append(heading, details, actions);
      proposals.append(card);
    }
  }

  function renderEntities(payload) {
    entityRows = Array.isArray(payload.entities) ? payload.entities : [];
    const list = id('entity-list');
    list.replaceChildren();
    for (const entity of entityRows) {
      const row = document.createElement('article');
      row.className = 'home-assistant-entity-row';
      row.dataset.search = [
        entity.name, entity.domain, entity.area,
        ...(entity.home_assistant_aliases || []), ...(entity.aliases || []),
      ].join(' ').toLocaleLowerCase();
      row.dataset.name = entity.name;

      const identity = document.createElement('div');
      identity.className = 'home-assistant-entity-identity';
      const heading = document.createElement('strong');
      heading.textContent = entity.name;
      const meta = document.createElement('small');
      const details = [entity.domain, entity.area, entity.state ? `state: ${entity.state}` : '']
        .filter(Boolean);
      meta.textContent = details.join(' · ');
      identity.append(heading, meta);
      if (!entity.available) {
        const unavailable = document.createElement('small');
        unavailable.className = 'addon-error';
        unavailable.textContent = 'No longer present in exposed MCP context';
        identity.append(unavailable);
      }

      const aliasLabel = document.createElement('label');
      aliasLabel.innerHTML = '<span>Call it… <small>Separate alternatives with commas</small></span>';
      const aliasInput = document.createElement('input');
      aliasInput.type = 'text';
      aliasInput.maxLength = 600;
      aliasInput.value = (entity.aliases || []).join(', ');
      aliasInput.placeholder = (entity.home_assistant_aliases || []).join(', ') || 'Optional everyday name';
      aliasInput.dataset.field = 'aliases';
      aliasLabel.append(aliasInput);

      const noteLabel = document.createElement('label');
      noteLabel.innerHTML = '<span>Meaning <small>Optional context for PETEY</small></span>';
      const noteInput = document.createElement('input');
      noteInput.type = 'text';
      noteInput.maxLength = 400;
      noteInput.value = entity.note || '';
      noteInput.placeholder = 'Example: automatic litter box in the laundry room';
      noteInput.dataset.field = 'note';
      noteLabel.append(noteInput);

      row.append(identity, aliasLabel, noteLabel);
      list.append(row);
    }
    id('entity-filter').disabled = false;
    id('save-vocabulary').disabled = false;
    id('vocabulary-status').textContent = `${entityRows.length} exposed entities loaded. Edit any rows, then choose Save all.`;
    applyEntityFilter();
  }

  function applyEntityFilter() {
    const query = id('entity-filter').value.trim().toLocaleLowerCase();
    for (const row of id('entity-list').querySelectorAll('.home-assistant-entity-row')) {
      row.hidden = Boolean(query && !row.dataset.search.includes(query));
    }
  }

  async function refresh() { render(await api('/status')); }

  async function run(button, operation) {
    button.disabled = true;
    try {
      await operation();
      await refresh();
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      button.disabled = false;
    }
  }

  id('save-connect').addEventListener('click', () => run(id('save-connect'), async () => {
    setStatus('Saving and connecting…');
    await api('/config', {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({base_url: id('url').value, token: id('token').value}),
    });
    id('token').value = '';
    await api('/connect', {method: 'POST'});
    setStatus('Connected to Home Assistant MCP.', 'success');
  }));
  id('reconnect').addEventListener('click', () => run(id('reconnect'), async () => {
    await api('/connect', {method: 'POST'});
    setStatus('Connected to Home Assistant MCP.', 'success');
  }));
  id('disconnect').addEventListener('click', () => run(id('disconnect'), async () => {
    await api('/disconnect', {method: 'POST'});
    setStatus('Disconnected.');
  }));
  id('clear-token').addEventListener('click', () => run(id('clear-token'), async () => {
    if (!window.confirm('Remove HOMEASSISTANT_TOKEN from PETEY’s .env file?')) return;
    await api('/token', {method: 'DELETE'});
    id('token').value = '';
    setStatus('Saved Home Assistant token removed.', 'success');
  }));
  id('trusted').addEventListener('change', event => {
    const trusted = event.currentTarget.checked;
    if (trusted && !window.confirm('Trust PETEY to run requested Home Assistant device changes immediately?')) {
      event.currentTarget.checked = false;
      return;
    }
    run(event.currentTarget, async () => {
      await api('/trust', {
        method: 'PUT', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({trusted}),
      });
      setStatus(trusted ? 'Trusted device actions enabled.' : 'Device changes require review.', 'success');
    });
  });
  id('refresh').addEventListener('click', () => run(id('refresh'), refresh));
  id('scan-entities').addEventListener('click', () => run(id('scan-entities'), async () => {
    id('vocabulary-status').textContent = 'Reading exposed entities…';
    renderEntities(await api('/entities'));
  }));
  id('save-vocabulary').addEventListener('click', () => run(id('save-vocabulary'), async () => {
    const entities = [...id('entity-list').querySelectorAll('.home-assistant-entity-row')]
      .map(row => ({
        name: row.dataset.name,
        aliases: row.querySelector('[data-field="aliases"]').value
          .split(',').map(value => value.trim()).filter(Boolean),
        note: row.querySelector('[data-field="note"]').value.trim(),
      }));
    const result = await api('/entity-vocabulary', {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({entities}),
    });
    id('vocabulary-status').textContent = `${result.vocabulary_count} customized entities saved.`;
  }));
  id('entity-filter').addEventListener('input', applyEntityFilter);
  window.addEventListener('petey:view', event => {
    if (event.detail.view === 'addon-home-assistant') run(id('refresh'), refresh);
  });
})();
