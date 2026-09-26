(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
  const callButton = document.querySelector('#call-button');
  const status = document.querySelector('#call-status');
  const logoutLink = document.querySelector('#logout-link');

  logoutLink?.addEventListener('click', async (event) => {
    event.preventDefault();
    const response = await fetch('/logout', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRF-Token': csrf },
    });
    if (response.redirected) window.location.assign(response.url);
  });

  callButton?.addEventListener('click', async () => {
    if (callButton.dataset.disabled === 'true') {
      status.textContent = 'Testmodus: Anrufe sind sicher deaktiviert.';
      status.dataset.state = 'warning';
      return;
    }
    callButton.disabled = true;
    callButton.dataset.loading = 'true';
    status.textContent = 'Der Anruf wird vorbereitet …';
    status.dataset.state = 'loading';
    try {
      const response = await fetch('/api/calls', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Accept': 'application/json',
          'X-CSRF-Token': csrf,
        },
      });
      const body = await response.json();
      status.textContent = body.message || 'Der Anruf konnte nicht gestartet werden.';
      status.dataset.state = body.accepted ? 'success' : 'error';
      if (!body.accepted) callButton.disabled = false;
    } catch (_error) {
      status.textContent = 'Keine Verbindung zum Dienst. Bitte versuchen Sie es später erneut.';
      status.dataset.state = 'error';
      callButton.disabled = false;
    } finally {
      callButton.dataset.loading = 'false';
    }
  });
})();
