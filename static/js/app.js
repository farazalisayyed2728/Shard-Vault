document.addEventListener('DOMContentLoaded', () => {
    // Password visibility toggle
    document.querySelectorAll('.toggle-password').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const input = document.getElementById(e.target.dataset.target);
            const isPassword = input.type === 'password';
            input.type = isPassword ? 'text' : 'password';
            e.target.textContent = isPassword ? 'Hide password' : 'Show password';
            e.target.setAttribute('aria-pressed', isPassword);
        });
    });

    // Mobile menu toggle
    const menuBtn = document.getElementById('mobile-menu-btn');
    const nav = document.getElementById('main-nav');
    if (menuBtn && nav) {
        menuBtn.addEventListener('click', () => {
            const expanded = menuBtn.getAttribute('aria-expanded') === 'true';
            menuBtn.setAttribute('aria-expanded', !expanded);
            nav.classList.toggle('open');
        });
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

document.getElementById('back-to-top')?.addEventListener('click', () => {
    window.scrollTo({top: 0, behavior: 'smooth'});
});