document.addEventListener('DOMContentLoaded', () => {
    const fileInput = document.getElementById('file-input');
    const uploadZone = document.getElementById('upload-zone');
    
    if(!fileInput) return;

    const csrfToken = document.cookie.split('; ').find(row => row.startsWith('csrftoken=')).split('=')[1];

    uploadZone.addEventListener('dragover', (e) => { e.preventDefault(); uploadZone.style.background = 'var(--bg-color)'; });
    uploadZone.addEventListener('dragleave', (e) => { uploadZone.style.background = 'transparent'; });
    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.style.background = 'transparent';
        if(e.dataTransfer.files.length) handleUpload(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change', (e) => { if(e.target.files.length) handleUpload(e.target.files[0]); });

    async function handleUpload(file) {
        document.getElementById('upload-progress-container').style.display = 'block';
        const progress = document.getElementById('upload-progress');
        
        // 1. Init
        const initRes = await fetch('/files/api/uploads/', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
            body: JSON.stringify({name: file.name, size: file.size, mime_type: file.type})
        });
        if(!initRes.ok) { alert("Upload init failed: " + (await initRes.json()).error); return; }
        const {upload_id, chunk_size} = await initRes.json();

        // 2. Upload chunks via XHR for progress
        const totalChunks = Math.ceil(file.size / chunk_size);
        for(let i=0; i<totalChunks; i++) {
            const chunk = file.slice(i * chunk_size, (i + 1) * chunk_size);
            await new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                xhr.open('PUT', `/files/api/uploads/${upload_id}/chunks/${i}/`);
                xhr.setRequestHeader('X-CSRFToken', csrfToken);
                xhr.upload.onprogress = e => {
                    if (e.lengthComputable) {
                        const chunkPct = (e.loaded / e.total) * (100 / totalChunks);
                        const basePct = (i / totalChunks) * 100;
                        progress.value = basePct + chunkPct;
                    }
                };
                xhr.onload = () => xhr.status === 200 ? resolve() : reject();
                xhr.send(chunk);
            });
        }

        // 3. Complete
        await fetch(`/files/api/uploads/${upload_id}/complete/`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
            body: JSON.stringify({sha256_checksum: 'client_hash_mock'}) // WebCrypto actual implementation reserved for refinement
        });
        window.location.reload();
    }
});

// App.js global additions (Scroll + Top + Search shortcut)
document.addEventListener('scroll', () => {
    const bar = document.getElementById('scroll-progress');
    const topBtn = document.getElementById('back-to-top');
    const winScroll = document.body.scrollTop || document.documentElement.scrollTop;
    const height = document.documentElement.scrollHeight - document.documentElement.clientHeight;
    if(bar) bar.style.width = (winScroll / height) * 100 + "%";
    if(topBtn) topBtn.style.display = winScroll > 300 ? 'block' : 'none';
});
document.addEventListener('keydown', e => {
    if(e.key === '/' && document.activeElement.tagName !== 'INPUT') {
        e.preventDefault();
        const search = document.getElementById('search-input');
        if(search) search.focus();
    }
});
document.getElementById('back-to-top')?.addEventListener('click', () => window.scrollTo({top:0, behavior:'smooth'}));