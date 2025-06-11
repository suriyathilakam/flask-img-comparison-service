# app.py
from flask import Flask, request, jsonify
import mysql.connector
from mysql.connector import Error
import hashlib
import io
from PIL import Image
import numpy as np
from werkzeug.utils import secure_filename
import os
from datetime import datetime

app = Flask(__name__)

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'your_database_name'),
    'user': os.getenv('DB_USER', 'your_username'),
    'password': os.getenv('DB_PASSWORD', 'your_password'),
    'port': int(os.getenv('DB_PORT', 3306))
}

# Allowed file extensions
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db_connection():
    """Create and return database connection"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        if connection.is_connected():
            return connection
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

def get_image_from_db(image_id):
    """Retrieve image blob from database by ID"""
    connection = get_db_connection()
    if not connection:
        return None
    
    try:
        cursor = connection.cursor()
        # Adjust table and column names according to your schema
        query = "SELECT image_data FROM images WHERE id = %s"
        cursor.execute(query, (image_id,))
        result = cursor.fetchone()
        
        if result and result[0]:
            return result[0]  # Return the blob data
        return None
        
    except Error as e:
        print(f"Error retrieving image from database: {e}")
        return None
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def compare_images_by_hash(img1_bytes, img2_bytes):
    """Compare two images using SHA-256 hash (exact comparison)"""
    if not img1_bytes or not img2_bytes:
        return False
    
    hash1 = hashlib.sha256(img1_bytes).hexdigest()
    hash2 = hashlib.sha256(img2_bytes).hexdigest()
    
    return hash1 == hash2

def compare_images_by_content(img1_bytes, img2_bytes, threshold=0.95):
    """Compare two images by converting to arrays and calculating similarity"""
    try:
        # Convert bytes to PIL Images
        img1 = Image.open(io.BytesIO(img1_bytes))
        img2 = Image.open(io.BytesIO(img2_bytes))
        
        # Resize images to same dimensions for comparison
        size = (256, 256)
        img1 = img1.resize(size, Image.Resampling.LANCZOS)
        img2 = img2.resize(size, Image.Resampling.LANCZOS)
        
        # Convert to RGB if needed
        if img1.mode != 'RGB':
            img1 = img1.convert('RGB')
        if img2.mode != 'RGB':
            img2 = img2.convert('RGB')
        
        # Convert to numpy arrays
        arr1 = np.array(img1)
        arr2 = np.array(img2)
        
        # Calculate similarity using normalized cross-correlation
        correlation = np.corrcoef(arr1.flatten(), arr2.flatten())[0, 1]
        
        # Handle NaN case
        if np.isnan(correlation):
            correlation = 0
        
        return correlation >= threshold, correlation
        
    except Exception as e:
        print(f"Error in content comparison: {e}")
        return False, 0.0

def compare_images_perceptual_hash(img1_bytes, img2_bytes, threshold=5):
    """Compare images using perceptual hashing (more robust for same image, different formats)"""
    try:
        # Convert bytes to PIL Images
        img1 = Image.open(io.BytesIO(img1_bytes))
        img2 = Image.open(io.BytesIO(img2_bytes))
        
        # Convert to grayscale and resize to 8x8
        img1 = img1.convert('L').resize((8, 8), Image.Resampling.LANCZOS)
        img2 = img2.convert('L').resize((8, 8), Image.Resampling.LANCZOS)
        
        # Convert to numpy arrays
        arr1 = np.array(img1)
        arr2 = np.array(img2)
        
        # Calculate average pixel value
        avg1 = np.mean(arr1)
        avg2 = np.mean(arr2)
        
        # Create binary hash
        hash1 = (arr1 > avg1).flatten()
        hash2 = (arr2 > avg2).flatten()
        
        # Calculate Hamming distance
        hamming_distance = np.sum(hash1 != hash2)
        
        # Images are similar if Hamming distance is below threshold
        is_similar = hamming_distance <= threshold
        similarity_score = 1 - (hamming_distance / 64)  # 64 bits total
        
        return is_similar, similarity_score, hamming_distance
        
    except Exception as e:
        print(f"Error in perceptual hash comparison: {e}")
        return False, 0.0, 64

def normalize_image_for_hash(img_bytes):
    """Normalize image to standard format for consistent hashing"""
    try:
        # Open image
        img = Image.open(io.BytesIO(img_bytes))
        
        # Ensure image is in a consistent format
        print(f"Original image mode: {img.mode}, size: {img.size}")
        
        # Convert to RGB
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Resize to standard size to eliminate size differences
        img = img.resize((512, 512), Image.Resampling.LANCZOS)
        
        # Save to bytes with consistent format and quality
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=95, optimize=True)
        
        return output.getvalue()
        
    except Exception as e:
        print(f"Error normalizing image: {e}")
        return img_bytes

def compare_images_normalized_hash(img1_bytes, img2_bytes):
    """Compare images using normalized hash (handles format differences)"""
    try:
        # Normalize both images
        norm_img1 = normalize_image_for_hash(img1_bytes)
        norm_img2 = normalize_image_for_hash(img2_bytes)
        
        # Compare hashes of normalized images
        hash1 = hashlib.sha256(norm_img1).hexdigest()
        hash2 = hashlib.sha256(norm_img2).hexdigest()
        
        return hash1 == hash2
        
    except Exception as e:
        print(f"Error in normalized hash comparison: {e}")
        return False

@app.route('/compare-image', methods=['POST'])
def compare_image():
    """
    API endpoint to compare uploaded image with database image
    Expected form data:
    - image_id: ID of the image in database
    - file: Image file to compare
    - comparison_method: 'hash', 'normalized_hash', 'perceptual', or 'content' (optional, defaults to 'perceptual')
    
    Comparison Methods:
    - hash: Exact byte comparison (strict, sensitive to format changes)
    - normalized_hash: Normalizes format then compares (handles JPG/JPEG differences)
    - perceptual: Uses perceptual hashing (best for same image, different formats)
    - content: Visual similarity using correlation (handles minor differences)
    """
    
    try:
        # Check if image_id is provided
        if 'image_id' not in request.form:
            return jsonify({
                'success': False,
                'message': 'image_id is required'
            }), 400
        
        image_id = request.form['image_id']
        
        # Check if file is provided
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'message': 'No file provided'
            }), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({
                'success': False,
                'message': 'No file selected'
            }), 400
        
        if not allowed_file(file.filename):
            return jsonify({
                'success': False,
                'message': 'File type not allowed'
            }), 400
        
        # Get comparison method (default to perceptual)
        comparison_method = request.form.get('comparison_method', 'hash')
        
        # Read uploaded file
        uploaded_file_bytes = file.read()
        
        # Get image from database
        db_image_bytes = get_image_from_db(image_id)
        
        if not db_image_bytes:
            return jsonify({
                'success': False,
                'message': 'Image not found in database'
            }), 404
        
        # Perform comparison based on method
        if comparison_method == 'hash':
            # Exact byte comparison
            is_same = compare_images_by_hash(db_image_bytes, uploaded_file_bytes)
            result = {
                'success': True,
                'is_same': is_same,
                'comparison_method': 'hash',
                'message': 'same' if is_same else 'not same',
                'note': 'Exact byte comparison - sensitive to format/compression differences'
            }
        
        elif comparison_method == 'normalized_hash':
            # Normalized hash comparison (handles format differences)
            is_same = compare_images_normalized_hash(db_image_bytes, uploaded_file_bytes)
            result = {
                'success': True,
                'is_same': is_same,
                'comparison_method': 'normalized_hash',
                'message': 'same' if is_same else 'not same',
                'note': 'Normalized comparison - handles JPG/JPEG format differences'
            }
        
        elif comparison_method == 'perceptual':
            # Perceptual hash comparison (most robust)
            is_same, similarity_score, hamming_distance = compare_images_perceptual_hash(db_image_bytes, uploaded_file_bytes)
            result = {
                'success': True,
                'is_same': is_same,
                'similarity_score': float(similarity_score),
                'hamming_distance': int(hamming_distance),
                'comparison_method': 'perceptual',
                'message': 'same' if is_same else 'not same',
                'note': 'Perceptual hash - best for same image with different formats/compression'
            }
        
        elif comparison_method == 'content':
            # Content similarity comparison
            is_same, similarity_score = compare_images_by_content(db_image_bytes, uploaded_file_bytes)
            result = {
                'success': True,
                'is_same': is_same,
                'similarity_score': float(similarity_score),
                'comparison_method': 'content',
                'message': 'same' if is_same else 'not same',
                'note': 'Content similarity - handles minor visual differences'
            }
        
        else:
            return jsonify({
                'success': False,
                'message': 'Invalid comparison method. Use "hash", "normalized_hash", "perceptual", or "content"'
            }), 400
        
        return jsonify(result), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Internal server error: {str(e)}'
        }), 500

@app.route('/upload-image', methods=['POST'])
def upload_image():
    """
    Helper endpoint to upload and store image in database
    Expected form data:
    - file: Image file to upload
    - name: Optional name for the image
    """
    
    try:
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'message': 'No file provided'
            }), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({
                'success': False,
                'message': 'No file selected'
            }), 400
        
        if not allowed_file(file.filename):
            return jsonify({
                'success': False,
                'message': 'File type not allowed'
            }), 400
        
        # Read file data
        file_data = file.read()
        filename = secure_filename(file.filename)
        image_name = request.form.get('name', filename)
        
        # Store in database
        connection = get_db_connection()
        if not connection:
            return jsonify({
                'success': False,
                'message': 'Database connection failed'
            }), 500
        
        try:
            cursor = connection.cursor()
            # Adjust table and column names according to your schema
            query = """
                INSERT INTO images (name, filename, image_data, upload_date) 
                VALUES (%s, %s, %s, %s)
            """
            cursor.execute(query, (image_name, filename, file_data, datetime.now()))
            connection.commit()
            
            image_id = cursor.lastrowid
            
            return jsonify({
                'success': True,
                'message': 'Image uploaded successfully',
                'image_id': image_id
            }), 201
            
        except Error as e:
            return jsonify({
                'success': False,
                'message': f'Database error: {str(e)}'
            }), 500
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Internal server error: {str(e)}'
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    }), 200

# Remove this block when using 'flask run'
# if __name__ == '__main__':
#     app.run(debug=True, host='0.0.0.0', port=5000)