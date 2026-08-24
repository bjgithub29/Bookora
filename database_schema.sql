-- ============================================
-- BOOKORA - CLEAN DATABASE SCHEMA
-- MySQL Database for Movie Booking System
-- ============================================

CREATE DATABASE IF NOT EXISTS bookora;
USE bookora;

-- ============================================
-- MOVIES TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS movies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    slug VARCHAR(100) UNIQUE NOT NULL,
    title VARCHAR(200) NOT NULL,
    language VARCHAR(100),
    duration INT,
    certification VARCHAR(10),
    genre VARCHAR(200),
    release_date DATE,
    poster_url VARCHAR(500),
    banner_url VARCHAR(500),
    description TEXT,
    director VARCHAR(200),
    cast TEXT,
    trailer_url VARCHAR(500),
    status VARCHAR(20) DEFAULT 'now_showing',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_slug (slug),
    INDEX idx_status (status)
);

-- ============================================
-- THEATRES TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS theatres (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    city VARCHAR(100) NOT NULL,
    address VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_city (city)
);

-- ============================================
-- SHOWS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS shows (
    id INT AUTO_INCREMENT PRIMARY KEY,
    movie_id INT NOT NULL,
    theatre_id INT NOT NULL,
    show_date DATE NOT NULL,
    show_time TIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
    FOREIGN KEY (theatre_id) REFERENCES theatres(id) ON DELETE CASCADE,
    INDEX idx_movie_date (movie_id, show_date),
    INDEX idx_theatre_date (theatre_id, show_date)
);

-- ============================================
-- SEATS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS seats (
    id INT AUTO_INCREMENT PRIMARY KEY,
    show_id INT NOT NULL,
    seat_label VARCHAR(10) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    is_booked BOOLEAN DEFAULT FALSE,
    booked_by INT NULL,
    booked_at TIMESTAMP NULL,
    FOREIGN KEY (show_id) REFERENCES shows(id) ON DELETE CASCADE,
    INDEX idx_show_id (show_id),
    INDEX idx_booked (is_booked),
    UNIQUE KEY unique_seat_per_show (show_id, seat_label)
);

-- ============================================
-- USERS TABLE (for auth - keep existing)
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(100) UNIQUE,
    phone VARCHAR(20) UNIQUE,
    primary_contact_type ENUM('email', 'phone') NOT NULL,
    role VARCHAR(20) DEFAULT 'user',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_contact CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

-- ============================================
-- OTP TABLE (for auth - keep existing)
-- ============================================
CREATE TABLE IF NOT EXISTS otp_verification (
    id INT AUTO_INCREMENT PRIMARY KEY,
    identifier VARCHAR(100) NOT NULL,
    otp VARCHAR(6) NOT NULL,
    expires_at DATETIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_identifier (identifier),
    INDEX idx_expires_at (expires_at)
);

-- ============================================
-- SAVED MOVIES TABLE (Junction Table)
-- ============================================
CREATE TABLE IF NOT EXISTS saved_movies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    movie_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_movie (user_id, movie_id),
    INDEX idx_user_id (user_id),
    INDEX idx_movie_id (movie_id)
);

-- ============================================
-- BOOKINGS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS bookings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    show_id INT NOT NULL,
    seat_ids JSON NOT NULL,
    total_price DECIMAL(10, 2) NOT NULL,
    status ENUM('CONFIRMED', 'CANCELLED') DEFAULT 'CONFIRMED',
    booking_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (show_id) REFERENCES shows(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_show_id (show_id),
    INDEX idx_status (status)
);

-- ============================================
-- SEED DATA - AHMEDABAD THEATRES
-- ============================================
INSERT INTO theatres (name, city, address) VALUES
('City Gold Cinema', 'Ahmedabad', 'CG Road, Ahmedabad'),
('Rajhans Cinemas', 'Ahmedabad', 'Vastrapur, Ahmedabad'),
('PVR Acropolis', 'Ahmedabad', 'Thaltej, Ahmedabad'),
('INOX Ahmedabad', 'Ahmedabad', 'SG Highway, Ahmedabad')
ON DUPLICATE KEY UPDATE name=name;

-- ============================================
-- PHONE NUMBER NORMALIZATION
-- Normalize all phone numbers to 10-digit format (remove +91 prefix)
-- ============================================
UPDATE users 
SET phone = CASE
    WHEN phone LIKE '+91%' THEN SUBSTRING(phone, 4)
    WHEN phone LIKE '91%' AND LENGTH(phone) = 12 THEN SUBSTRING(phone, 3)
    ELSE phone
END
WHERE phone IS NOT NULL;
