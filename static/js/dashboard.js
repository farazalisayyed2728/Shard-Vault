async function pollClusterStatus() {
    if (document.hidden) return;

    const list = document.getElementById('node-status-list');
    if (!list) return;

    try {
        const response = await fetch('/files/api/status/', {
            headers: {'Accept': 'application/json'}
        });
        if (!response.ok) {
            throw new Error(`Cluster status request failed: ${response.status}`);
        }

        const data = await response.json();
        list.replaceChildren();
        for (const node of data.nodes) {
            const item = document.createElement('li');
            item.append(document.createTextNode(`${node.name}: `));
            const status = document.createElement('span');
            status.textContent = node.status;
            status.style.color = node.status === 'healthy'
                ? 'var(--success-color)'
                : 'var(--error-color)';
            item.append(status);
            list.append(item);
        }
        if (data.nodes.length === 0) {
            const item = document.createElement('li');
            item.textContent = 'No storage nodes registered';
            list.append(item);
        }
        document.getElementById('repair-count').textContent = data.under_replicated;
    } catch (error) {
        console.error('Could not load cluster status', error);
        list.replaceChildren();
        const item = document.createElement('li');
        item.textContent = 'Cluster status unavailable';
        list.append(item);
    }
}

setInterval(pollClusterStatus, 10000);
pollClusterStatus();
