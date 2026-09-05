/**
 * Seat Selection Page - Clean Database-Driven Implementation
 * No static JSON, no fallbacks, pure MySQL data
 */

// ==========================================
// AUTHENTICATION CHECK (Reused from Shows page)
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
// SEAT SELECTION LOGIC
// ==========================================

// Get show ID from URL
const showId = window.location.pathname.split('/').pop();
let showData = null;
let seatsData = [];
let selectedSeats = [];

// Load show and seats
async function loadShowAndSeats() {
    try {
        const response = await fetch(`/api/seats/${showId}`);
        const data = await response.json();
        
        if (!data.success) {
            throw new Error(data.message);
        }
        
        showData = data.show;
        seatsData = data.seats;
        
        // Update UI
        document.getElementById('movieTitle').textContent = showData.movie_title;
        document.getElementById('showDetails').innerHTML = `
            ${showData.theatre_name} • ${showData.theatre_address}<br>
            ${formatShowDate(showData.show_date)} • ${formatShowTime(showData.show_time)}
        `;
        
        document.title = `${showData.movie_title} - Select Seats - Bookora`;
        
        // Render seats
        renderSeats();
        
    } catch (error) {
        console.error('Error loading seats:', error);
        document.getElementById('movieTitle').textContent = 'Error Loading Seats';
        document.getElementById('showDetails').textContent = error.message;
    }
}

// Format helpers
function formatShowDate(dateStr) {
    const date = new Date(dateStr);
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return `${days[date.getDay()]}, ${months[date.getMonth()]} ${date.getDate()}`;
}

function formatShowTime(timeStr) {
    // timeStr is HH:MM format
    return timeStr;
}

// Render seats
function renderSeats() {
    const container = document.getElementById('seatsContainer');
    
    // Group seats by row
    const rows = {};
    seatsData.forEach(seat => {
        const row = seat.seat_label[0]; // First character is row letter
        if (!rows[row]) {
            rows[row] = [];
        }
        rows[row].push(seat);
    });
    
    // Render rows in order (A, B, C, ...). Within each row, sort seats by their
    // numeric position so 2 comes before 10 — string sorting would order the
    // labels as "A1, A10, A11, A12, A2..." and show 1,10,11,12,2,3 on screen.
    const rowKeys = Object.keys(rows).sort();
    rowKeys.forEach(row => {
        rows[row].sort((a, b) =>
            parseInt(a.seat_label.substring(1), 10) - parseInt(b.seat_label.substring(1), 10)
        );
    });
    container.innerHTML = rowKeys.map(row => `
        <div class="seat-row">
            <div class="row-label">${row}</div>
            <div class="seats">
                ${rows[row].map(seat => `
                    <div 
                        class="seat ${getSeatClass(seat)}"
                        data-seat-id="${seat.id}"
                        data-seat-label="${seat.seat_label}"
                        data-price="${seat.price}"
                        onclick="toggleSeat(${seat.id}, '${seat.seat_label}', ${seat.price}, ${seat.is_booked})"
                        ${seat.is_booked ? 'disabled' : ''}
                    >
                        ${seat.seat_label.substring(1)}
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('');
}

// Get seat CSS class
function getSeatClass(seat) {
    if (seat.is_booked) return 'booked-seat';
    if (selectedSeats.includes(seat.id)) return 'selected-seat';
    return 'available-seat';
}

// Toggle seat selection
function toggleSeat(seatId, seatLabel, price, isBooked) {
    if (isBooked) return;
    
    const index = selectedSeats.indexOf(seatId);
    
    if (index > -1) {
        // Deselect
        selectedSeats.splice(index, 1);
    } else {
        // Select
        selectedSeats.push(seatId);
    }
    
    // Re-render seats
    renderSeats();
    
    // Update summary
    updateBookingSummary();
}

// Update booking summary
function updateBookingSummary() {
    const summary = document.getElementById('bookingSummary');
    const selectedSeatsText = document.getElementById('selectedSeatsText');
    const totalPriceElem = document.getElementById('totalPrice');
    
    if (selectedSeats.length === 0) {
        summary.style.display = 'none';
        return;
    }
    
    summary.style.display = 'block';
    
    // Get selected seat details
    const selectedSeatDetails = seatsData.filter(s => selectedSeats.includes(s.id));
    const seatLabels = selectedSeatDetails.map(s => s.seat_label).join(', ');
    const totalPrice = selectedSeatDetails.reduce((sum, s) => sum + parseFloat(s.price), 0);
    
    selectedSeatsText.textContent = `${selectedSeats.length} seat${selectedSeats.length > 1 ? 's' : ''}: ${seatLabels}`;
    totalPriceElem.textContent = totalPrice.toFixed(0);
}

// Proceed to payment
// Proceed to payment - REQUIRE LOGIN HERE (BookMyShow-style)
async function proceedToPayment() {
    if (selectedSeats.length === 0) {
        alert('Please select at least one seat');
        return;
    }
    
    // Check if user is logged in
    const user = JSON.parse(localStorage.getItem('bookoraUser') || 'null');
    
    if (!user) {
        // User not logged in - open sign-in modal for payment
        if (typeof openSignInModal === 'function') {
            // Store booking data for after login
            const bookingData = {
                show_id: showId,
                show_data: showData,
                selected_seats: selectedSeats,
                seat_details: seatsData.filter(s => selectedSeats.includes(s.id)),
                total_price: seatsData.filter(s => selectedSeats.includes(s.id)).reduce((sum, s) => sum + parseFloat(s.price), 0)
            };
            sessionStorage.setItem('bookora_pending_booking', JSON.stringify(bookingData));
            
            openSignInModal('booking');
        } else {
            alert('Please sign in to complete your booking');
        }
        return;
    }
    
    // User is logged in - show confirmation modal
    const seatDetails = seatsData.filter(s => selectedSeats.includes(s.id));
    const totalPrice = seatDetails.reduce((sum, s) => sum + parseFloat(s.price), 0);
    
    showBookingConfirmationModal(seatDetails, totalPrice);
}

// Show booking confirmation modal
function showBookingConfirmationModal(seatDetails, totalPrice) {
    const modal = document.getElementById('bookingConfirmModal');
    const content = document.getElementById('bookingConfirmContent');
    
    // Check if all seats have same price
    const uniquePrices = [...new Set(seatDetails.map(s => parseFloat(s.price)))];
    const hasMixedPricing = uniquePrices.length > 1;
    
    // Format show date and time
    const showDate = formatShowDate(showData.show_date);
    const showTime = formatShowTime(showData.show_time);
    
    // Build seat pricing details
    let seatPricingHTML = '';
    if (hasMixedPricing) {
        // Show individual seat prices
        seatPricingHTML = seatDetails.map(seat => {
            const seatType = seat.seat_type ? ` (${seat.seat_type})` : '';
            return `
            <div class="seat-price-item">
                <span>${seat.seat_label}${seatType}</span>
                <span>₹${parseFloat(seat.price).toFixed(2)}</span>
            </div>
        `;
        }).join('');
    } else {
        // Show single price with all seats
        const seatLabels = seatDetails.map(s => s.seat_label).join(', ');
        seatPricingHTML = `
            <div class="seat-price-item">
                <span>${seatDetails.length} Seat${seatDetails.length > 1 ? 's' : ''}: ${seatLabels}</span>
                <span>₹${parseFloat(seatDetails[0].price).toFixed(2)} each</span>
            </div>
        `;
    }
    
    // Build confirmation content
    content.innerHTML = `
        <div class="booking-detail-row">
            <span class="booking-detail-label">Movie</span>
            <span class="booking-detail-value">${showData.movie_title}</span>
        </div>
        <div class="booking-detail-row">
            <span class="booking-detail-label">Venue</span>
            <span class="booking-detail-value">${showData.theatre_name}</span>
        </div>
        <div class="booking-detail-row">
            <span class="booking-detail-label">Show Time</span>
            <span class="booking-detail-value">${showDate}, ${showTime}</span>
        </div>
        <div class="booking-detail-row seats-pricing">
            <span class="booking-detail-label">Seats & Pricing</span>
            <div class="seat-pricing-list">
                ${seatPricingHTML}
            </div>
        </div>
        <div class="booking-detail-row total-row">
            <span class="booking-detail-label">Total Amount</span>
            <span class="booking-detail-value highlight">₹${totalPrice.toFixed(2)}</span>
        </div>
    `;
    
    // Store booking data for confirmation
    window.pendingBookingData = {
        seatDetails,
        totalPrice
    };
    
    // Show modal - prevent closing by click outside or Esc
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
    
    // Disable closing by clicking outside
    modal.onclick = (e) => {
        if (e.target === modal) {
            // Do nothing - user must click OK
            e.stopPropagation();
        }
    };
    
    // Disable Esc key
    document.addEventListener('keydown', preventEscClose);
}

// Prevent Esc key from closing modal
function preventEscClose(e) {
    if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
    }
}

// Close booking confirmation modal
function closeBookingConfirmModal() {
    const modal = document.getElementById('bookingConfirmModal');
    modal.classList.remove('active');
    document.body.style.overflow = 'auto';
    
    // Remove Esc key prevention
    document.removeEventListener('keydown', preventEscClose);
    
    // Clear pending booking data
    window.pendingBookingData = null;
}

// Confirm booking
async function confirmBooking() {
    const user = JSON.parse(localStorage.getItem('bookoraUser') || 'null');
    if (!user || !window.pendingBookingData) return;
    
    const { seatDetails, totalPrice } = window.pendingBookingData;
    const button = document.getElementById('confirmBookingBtn');
    const content = document.getElementById('bookingConfirmContent');
    const actions = document.getElementById('confirmActions');
    
    // Show verification loader
    button.disabled = true;
    content.innerHTML = `
        <div class="verification-loader">
            <div class="spinner"></div>
            <p class="verification-text">Processing your booking...</p>
        </div>
    `;
    actions.style.display = 'none';
    
    try {
        // Relative URL + session cookie: the server derives the user from the
        // session, not from the request body. total_price is also recomputed
        // server-side, so the client value here is not trusted.
        const response = await fetch('/api/create-booking', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                show_id: showId,
                seat_ids: selectedSeats
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Show success state
            setTimeout(() => {
                content.innerHTML = `
                    <div class="booking-success-content">
                        <div class="success-icon">🎉</div>
                        <h3 class="success-title">Booking Confirmed!</h3>
                        <p class="success-message">Your tickets have been booked successfully.<br>You can view details in My Bookings section.</p>
                    </div>
                `;
                
                // Auto-redirect after 3 seconds
                setTimeout(() => {
                    window.location.href = '/my-bookings';
                }, 3000);
            }, 1500);
        } else {
            // Show error and allow retry
            content.innerHTML = `
                <div class="booking-error-content" style="text-align: center; padding: 2rem; color: #d32f2f;">
                    <i class="fas fa-exclamation-circle" style="font-size: 3rem; margin-bottom: 1rem;"></i>
                    <p>${data.message || 'Failed to create booking. Please try again.'}</p>
                </div>
            `;
            actions.style.display = 'flex';
            button.disabled = false;
        }
    } catch (error) {
        console.error('Error creating booking:', error);
        content.innerHTML = `
            <div class="booking-error-content" style="text-align: center; padding: 2rem; color: #d32f2f;">
                <i class="fas fa-exclamation-circle" style="font-size: 3rem; margin-bottom: 1rem;"></i>
                <p>An error occurred. Please try again.</p>
            </div>
        `;
        actions.style.display = 'flex';
        button.disabled = false;
    }
}

// Initialize
checkAuth(); // Check auth state on page load
loadShowAndSeats();
