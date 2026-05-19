document.addEventListener('DOMContentLoaded', () => {
  // --- Navigation & Account Menu Logic ---
  const navToggle = document.querySelector('.nav-toggle');
  const nav = document.querySelector('.top-nav');
  const accountToggle = document.querySelector('.account-toggle');
  const accountMenu = document.querySelector('.account-dropdown');

  const isMobile = () => window.matchMedia('(max-width: 860px)').matches;

  const closeNav = () => {
    if (!nav || !navToggle) return;
    nav.classList.remove('is-open');
    navToggle.setAttribute('aria-expanded', 'false');
  };

  const closeAccount = () => {
    if (!accountMenu || !accountToggle) return;
    accountMenu.classList.remove('is-open');
    accountMenu.hidden = true;
    accountToggle.setAttribute('aria-expanded', 'false');
  };

  if (navToggle && nav) {
    navToggle.addEventListener('click', () => {
      const willOpen = !nav.classList.contains('is-open');
      nav.classList.toggle('is-open', willOpen);
      navToggle.setAttribute('aria-expanded', String(willOpen));
      if (willOpen) closeAccount();
    });

    nav.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', () => {
        if (isMobile()) closeNav();
      });
    });
  }

  if (accountToggle && accountMenu) {
    accountToggle.addEventListener('click', () => {
      const willOpen = accountMenu.hidden;
      accountMenu.hidden = !willOpen;
      accountMenu.classList.toggle('is-open', willOpen);
      accountToggle.setAttribute('aria-expanded', String(willOpen));
      if (willOpen) closeNav();
    });

    accountMenu.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', closeAccount);
    });
  }

  document.addEventListener('click', (event) => {
    if (nav && navToggle && !nav.contains(event.target) && !navToggle.contains(event.target)) {
      if (isMobile()) closeNav();
    }
    if (accountMenu && accountToggle && !accountMenu.contains(event.target) && !accountToggle.contains(event.target)) {
      closeAccount();
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeNav();
      closeAccount();
    }
  });

  window.addEventListener('resize', () => {
    closeNav();
    closeAccount();
  });

  // --- Sticky Header Shadow & Back to Top Logic ---
  const header = document.querySelector('.site-header');
  const backToTopBtn = document.querySelector('.back-to-top');
  const scrollThreshold = 300; 

  const handleScroll = () => {
    // Toggle header shadow
    header.classList.toggle('scrolled', window.scrollY > 10);

    // Toggle Back to Top button
    if (backToTopBtn) {
      backToTopBtn.classList.toggle('visible', window.scrollY > scrollThreshold);
    }
  };

  window.addEventListener('scroll', handleScroll);

  if (backToTopBtn) {
    backToTopBtn.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  handleScroll(); // Initial check
});