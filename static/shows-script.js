/**
 * Shows Page - Clean Database-Driven Implementation
 * No static JSON, no fallbacks, pure MySQL data
 */

// Get movie slug from URL
const movieSlug = window.location.pathname.split('/').pop();
let movieData = null;
let selectedDate = getTodayDate();

console.log('🎬 SHOWS PAGE INITIALIZED');
console.log('   → Movie slug from URL:', movieSlug);
console.log('   → Initial selected date:', selectedDate);

// ==========================================
// AUTHENTICATION CHECK
// ==========================================

function checkAuth() {
    const user = JSON.parse(localStorage.getItem('bookoraUser') || 'null');
    
    if (user) {
        // User is logged in
        document.getElementById('loggedOutState').style.display = 'none';
        document.getElementById('loggedInState').style.display = 'flex';
        
        // Update profile info
        const displayName = user.name || 'User';
        const displayContact = user.email || user.phone || '';
        
        document.getElementById('profileDisplayName').textContent = displayName;
        document.getElementById('profileDisplayContact').textContent = displayContact;
    } else {
        // User is logged out
        document.getElementById('loggedOutState').style.display = 'flex';
        document.getElementById('loggedInState').style.display = 'none';
    }
}

// Profile dropdown toggle
function toggleProfileDropdown() {
    const dropdown = document.getElementById('profileDropdown');
    dropdown.classList.toggle('active');
}

// Navigation functions
function navigateToProfile(event) {
    event.preventDefault();
    window.location.href = '/profile';
}

function navigateToBookings(event) {
    event.preventDefault();
    window.location.href = '/my-bookings';
}

function navigateToSavedMovies(event) {
    event.preventDefault();
    window.location.href = '/saved-movies';
}

function handleLogout(event) {
    event.preventDefault();
    
    // Get user name before clearing
    const user = getCurrentUser();
    const userName = user ? user.name : 'User';
    
    // Clear user data from localStorage
    logoutUser();
    
    // Clear any temporary session data
    sessionStorage.removeItem('tempMobile');
    sessionStorage.removeItem('tempEmail');
    
    // Close dropdown
    const dropdown = document.getElementById('profileDropdown');
    if (dropdown) {
        dropdown.classList.remove('active');
    }
    
    // Show logout confirmation toast
    showLogoutConfirmation(userName);
    
    console.log('User logged out successfully - all state cleared');
}

// Close dropdown when clicking outside
document.addEventListener('click', function(e) {
    const profileContainer = document.querySelector('.profile-container');
    const dropdown = document.getElementById('profileDropdown');
    
    if (profileContainer && dropdown && !profileContainer.contains(e.target)) {
        dropdown.classList.remove('active');
    }
});

// ==========================================
// DATE HELPERS
// ==========================================

// Date helpers
function getTodayDate() {
    return new Date().toISOString().split('T')[0];
}

function formatDateForDisplay(dateStr) {
    const date = new Date(dateStr + 'T00:00:00'); // Add time to avoid timezone issues
    const days = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
    const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
    
    const dayName = days[date.getDay()];
    const monthName = months[date.getMonth()];
    const dayNum = date.getDate();
    
    return `${dayName}, ${monthName} ${dayNum}`;
}

function getNextDates(count = 7) {
    const dates = [];
    for (let i = 0; i < count; i++) {
        const date = new Date();
        date.setDate(date.getDate() + i);
        dates.push(date.toISOString().split('T')[0]);
    }
    return dates;
}

// Convert 24-hour time to 12-hour format with AM/PM
function formatTimeTo12Hour(time24) {
    const [hours, minutes] = time24.split(':').map(Number);
    const period = hours >= 12 ? 'PM' : 'AM';
    const hours12 = hours % 12 || 12;
    return `${hours12}:${minutes.toString().padStart(2, '0')} ${period}`;
}

// ==========================================
// LOAD MOVIE DETAILS
// ==========================================

// Load movie details
async function loadMovie() {
    try {
        console.log('\n📡 LOADING MOVIE DATA...');
        console.log('   → Fetching from:', `/api/movies/slug/${movieSlug}`);
        
        const response = await fetch(`/api/movies/slug/${movieSlug}`);
        const data = await response.json();
        
        console.log('   → API Response:', data);
        
        if (!data.success) {
            throw new Error(data.message);
        }
        
        movieData = data.movie;
        
        console.log('   ✅ Movie loaded:', {
            id: movieData.id,
            title: movieData.title,
            slug: movieData.slug
        });
        
        // Update UI
        document.getElementById('movieTitle').textContent = movieData.title;
        document.getElementById('movieDetails').textContent = 
            `${movieData.language} • ${movieData.duration} min • ${movieData.certification}`;
        
        document.title = `${movieData.title} - Select Show - Bookora`;
        
        // Render date buttons
        renderDateButtons();
        
        // Load shows for today
        loadShows();
        
    } catch (error) {
        console.error('❌ Error loading movie:', error);
        document.getElementById('movieTitle').textContent = 'Error Loading Movie';
        document.getElementById('movieDetails').textContent = error.message;
    }
}

// ==========================================
// RENDER DATE BUTTONS
// ==========================================

// Render date buttons
function renderDateButtons() {
    const container = document.getElementById('dateButtons');
    const dates = getNextDates(7);
    
    container.innerHTML = dates.map(date => `
        <button 
            class="date-btn ${date === selectedDate ? 'active' : ''}"
            onclick="selectDate('${date}')"
        >
            ${formatDateForDisplay(date)}
        </button>
    `).join('');
}

// Select date
function selectDate(date) {
    selectedDate = date;
    renderDateButtons();
    loadShows();
}

// ==========================================
// LOAD SHOWS
// ==========================================

// Load shows
async function loadShows() {
    const container = document.getElementById('theatresContainer');
    container.innerHTML = '<div class="shows-loading">Loading shows...</div>';
    
    try {
        console.log('\n🎭 LOADING SHOWS...');
        console.log('   → Movie ID:', movieData.id);
        console.log('   → Movie Slug:', movieData.slug);
        console.log('   → Selected Date:', selectedDate);
        
        // Use slug parameter (backend will resolve to ID)
        const apiUrl = `/api/shows?slug=${movieData.slug}&date=${selectedDate}`;
        console.log('   → Fetching from:', apiUrl);
        
        const response = await fetch(apiUrl);
        const data = await response.json();
        
        console.log('   → API Response:', data);
        
        if (!data.success) {
            throw new Error(data.message);
        }
        
        if (!data.theatres || data.theatres.length === 0) {
            console.log('   ⚠️  No shows available for this date');
            container.innerHTML = `
                <div class="no-shows">
                    <h3>No Shows Available</h3>
                    <p>There are no shows scheduled for this date. Please select another date.</p>
                </div>
            `;
            return;
        }
        
        console.log(`   ✅ Received ${data.theatres.length} theatres with shows:`);
        data.theatres.forEach(theatre => {
            console.log(`      → ${theatre.name}: ${theatre.shows.length} shows`);
        });
        
        // Get current date and time for expiry checking
        const currentDateTime = new Date();
        
        // Render theatres
        container.innerHTML = data.theatres.map(theatre => `
            <div class="theatre-card">
                <div class="theatre-name">${theatre.name}</div>
                <div class="theatre-location">${theatre.address}</div>
                <div class="showtimes">
                    ${theatre.shows.map(show => {
                        // Check if show has expired
                        const showDateTime = new Date(`${show.show_date}T${show.time}:00`);
                        const isExpired = currentDateTime >= showDateTime;
                        const isSoldOut = show.available_seats === 0;
                        const isDisabled = isExpired || isSoldOut;
                        
                        // Format time to 12-hour format
                        const formattedTime = formatTimeTo12Hour(show.time);
                        
                        return `
                        <button 
                            class="showtime-btn ${isExpired ? 'show-expired' : ''} ${isSoldOut ? 'disabled' : ''}"
                            onclick="selectShow(${show.show_id})"
                            ${isDisabled ? 'disabled' : ''}
                        >
                            <div>${formattedTime}</div>
                            <div class="seats-info">
                                ${isExpired 
                                    ? '<small class="booking-closed">Booking Closed</small>' 
                                    : `${show.available_seats} seats`
                                }
                            </div>
                        </button>
                        `;
                    }).join('')}
                </div>
            </div>
        `).join('');
        
        console.log('   ✅ Shows rendered successfully\n');
        
    } catch (error) {
        console.error('❌ Error loading shows:', error);
        container.innerHTML = `<div class="error-msg">Error loading shows: ${error.message}</div>`;
    }
}

// ==========================================
// SELECT SHOW
// ==========================================

// Select show - navigate to seats page
function selectShow(showId) {
    window.location.href = `/seats/${showId}`;
}

// ==========================================
// INITIALIZE
// ==========================================

// Check auth state on page load
checkAuth();

// Initialize
loadMovie();
