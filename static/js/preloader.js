class LiquidGlassPreloader {
    constructor() {
        this.preloader = document.getElementById('liquid-glass-preloader');
        this.progressBar = document.getElementById('progress-bar');
        this.percentage = document.getElementById('percentage');
        this.progress = 0;
        this.duration = 1000;
        this.startTime = null;
        
        this.init();
    }

    init() {
        this.startTime = Date.now();
        this.animateProgress();
    }

    animateProgress() {
        const animate = () => {
            const currentTime = Date.now();
            const elapsed = currentTime - this.startTime;
            this.progress = Math.min((elapsed / this.duration) * 100, 100);
            
            this.updateProgress(this.progress);
            
            if (this.progress < 100) {
                requestAnimationFrame(animate);
            } else {
                setTimeout(() => this.hide(), 300);
            }
        };
        
        animate();
    }

    updateProgress(percent) {
        this.progress = Math.min(100, Math.max(0, percent));
        this.progressBar.style.width = this.progress + '%';
        this.percentage.textContent = Math.round(this.progress) + '%';
    }

    hide() {
        this.preloader.classList.add('preloader-fade-out');
        setTimeout(() => {
            if (this.preloader && this.preloader.parentNode) {
                this.preloader.parentNode.removeChild(this.preloader);
            }
        }, 500);
    }
}

const preloaderHTML = `
    <div id="liquid-glass-preloader">
        <div class="preloader-content">
            <div class="app-title">CryptoPay</div>
            <div class="progress-container">
                <div class="progress-bar" id="progress-bar"></div>
            </div>
            <div class="percentage" id="percentage">0%</div>
        </div>
    </div>
`;

document.addEventListener('DOMContentLoaded', function() {
    if (!document.querySelector('link[href*="liquid-glass-preloader.css"]')) {
        console.warn('CSS файл для прелоадера не найден. Убедитесь, что liquid-glass-preloader.css подключен.');
    }
    
    document.body.insertAdjacentHTML('afterbegin', preloaderHTML);
    
    new LiquidGlassPreloader();
});

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
        document.body.insertAdjacentHTML('afterbegin', preloaderHTML);
        new LiquidGlassPreloader();
    });
} else {
    document.body.insertAdjacentHTML('afterbegin', preloaderHTML);
    new LiquidGlassPreloader();
}