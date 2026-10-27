document.addEventListener('DOMContentLoaded', () => {
    const fileInput = document.getElementById('file-input');
    const uploadZone = document.getElementById('upload-zone');
    
    if (!fileInput || !uploadZone) return;

    const csrfCookie = document.cookie.split('; ').find(row => row.startsWith('csrftoken='));
    const csrfToken = csrfCookie ? csrfCookie.split('=')[1] : null;
    const status = document.getElementById('upload-status');

    uploadZone.addEventListener('dragover', (e) => { e.preventDefault(); uploadZone.style.background = 'var(--bg-color)'; });
    uploadZone.addEventListener('dragleave', (e) => { uploadZone.style.background = 'transparent'; });
    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.style.background = 'transparent';
        if(e.dataTransfer.files.length) handleUpload(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change', (e) => { if(e.target.files.length) handleUpload(e.target.files[0]); });

    async function handleUpload(file) {
        if (!csrfToken) {
            if (status) status.textContent = 'Upload failed: missing security token. Refresh the page and try again.';
            return;
        }

        document.getElementById('upload-progress-container').style.display = 'block';
        const progress = document.getElementById('upload-progress');
        if (status) status.textContent = 'Preparing upload...';

        try {
            const initRes = await fetch('/files/api/uploads/', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
                body: JSON.stringify({name: file.name, size: file.size, mime_type: file.type})
            });
            const initData = await initRes.json();
            if (!initRes.ok) throw new Error(initData.error || 'Upload initialization failed');
            const {upload_id, chunk_size} = initData;

            const totalChunks = Math.ceil(file.size / chunk_size);
            for (let i = 0; i < totalChunks; i++) {
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
                    xhr.onload = () => {
                        if (xhr.status === 200) resolve();
                        else {
                            try {
                                reject(new Error(JSON.parse(xhr.responseText).error || 'Chunk upload failed'));
                            } catch (error) {
                                reject(error instanceof SyntaxError ? new Error('Chunk upload failed') : error);
                            }
                        }
                    };
                    xhr.onerror = () => reject(new Error('Network error while uploading chunk'));
                    xhr.send(chunk);
                });
            }

            const fileBuffer = await file.arrayBuffer();
            const digest = await crypto.subtle.digest('SHA-256', fileBuffer);
            const checksum = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
            const completeResponse = await fetch(`/files/api/uploads/${upload_id}/complete/`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
                body: JSON.stringify({sha256_checksum: checksum})
            });
            const completeData = await completeResponse.json();
            if (!completeResponse.ok) throw new Error(completeData.error || 'Could not complete upload');
            window.location.reload();
        } catch (error) {
            console.error('Upload failed', error);
            if (status) status.textContent = `Upload failed: ${error.message}`;
        }
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