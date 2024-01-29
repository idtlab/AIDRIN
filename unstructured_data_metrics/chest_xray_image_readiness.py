import io
import base64
import matplotlib.pyplot as plt
import numpy as np
import re
from io import BytesIO
import cv2

def calculate_cnr_from_dicom(dicom_data):
    
    # Read DICOM file

    # Extract pixel array
    pixel_array = dicom_data.pixel_array

    # Calculate mean and standard deviation for the entire image
    image_mean, image_std = np.mean(pixel_array), np.std(pixel_array)

    hist, bins, _ = plt.hist(pixel_array.flatten(), bins=256, range=[0, 256], density=False)
    
    # Create a figure with two subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6))

    # Plot the intensity distribution
    ax1.bar(bins[:-1], hist, width=1, color='blue', alpha=0.7)
    ax1.set_title('Intensity Distribution')
    ax1.set_xlabel('Intensity')
    ax1.set_ylabel('Frequency')

    # Plot the original image
    ax2.imshow(pixel_array, cmap='gray')
    ax2.set_title('Original Image')
    ax2.axis('off')  # Turn off axis labels and ticks

    # Save the plot to a BytesIO object
    image_stream = io.BytesIO()
    plt.savefig(image_stream, format='png')
    plt.close(fig)

    # Move the "cursor" to the beginning of the BytesIO stream
    image_stream.seek(0)

    # Read the binary data from the stream
    binary_data = image_stream.read()

    # Encode the binary data to Base64
    base64_encoded = base64.b64encode(binary_data).decode('utf-8')

    # Calculate CNR for the entire image
    cnr = (image_mean - 0) / image_std  # Assuming 0 as background intensity

    cnr_dict = {
        'Mean Intensity': image_mean,
        'Standard Deviation (Quantum Noise)': image_std,
        'Contrast to Noise Ratio (CNR)': cnr,
        "Intensity Distribution Visualization": base64_encoded
    }
    return cnr_dict

def calculate_spatial_resolution(dicom_dataset):
    # Read the DICOM file
    # dicom_dataset = pydicom.dcmread(file_path,force=True)

    # Extract pixel spacing
    pixel_spacing = dicom_dataset.get('PixelSpacing', None)

    if pixel_spacing is not None and len(pixel_spacing) == 2:
        # Calculate spatial resolution
        spatial_resolution_x = 1 / float(pixel_spacing[0])
        spatial_resolution_y = 1 / float(pixel_spacing[1])
        return {"Spatial Resolution X":spatial_resolution_x,"Spatial Resolution Y": spatial_resolution_y}
    else:
        return {"Spatial Resolution X":"Unavailable","Spatial Resolution Y": "Unavailable"}


def detect_and_visualize_artifacts(dicom_data):
    # Load DICOM image
    # dicom_data = pydicom.dcmread(dicom_file_path, force=True)

    image_array = dicom_data.pixel_array

    # Apply GaussianBlur to reduce noise and improve thresholding
    blurred = cv2.GaussianBlur(image_array, (5, 5), 0)

    # Apply adaptive thresholding
    artifact_mask = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2
    )

    # Create a plot
    plt.figure(figsize=(14, 8))

    # Plot the original image
    plt.subplot(1, 3, 1)
    plt.imshow(image_array, cmap='gray')
    plt.axis('off')
    plt.title('Original Image')

    # Plot the adaptive thresholded image
    plt.subplot(1, 3, 2)
    plt.imshow(artifact_mask, cmap='gray')
    plt.axis('off')
    plt.title('Artifact Mask')

    # Plot the image with artifacts
    image_with_artifacts = np.copy(image_array)
    image_with_artifacts[artifact_mask == 255] = np.max(image_array)  # Set artifact pixels to the maximum
    plt.subplot(1, 3, 3)
    plt.imshow(image_with_artifacts, cmap='gray')
    plt.axis('off')
    plt.title(f'Image with Artifacts usign adaptive thresholding')

    # Save the plot to a BytesIO object
    image_stream = io.BytesIO()
    plt.savefig(image_stream, format='png')
    plt.close()

    # Encode the BytesIO content as base64
    encoded_image = base64.b64encode(image_stream.getvalue()).decode('utf-8')

    return {
        "Image with Artifacts": encoded_image,
        "Description": "Identifies artifact pixels using adaptive thresholding.",
    }

    # # Return the base64-encoded images
    # original_image_base64 = plot_to_base64(image_array)
    # image_with_artifacts_base64 = plot_to_base64(image_with_artifacts)

    # return {"Image with Artifacts":image_with_artifacts_base64, "Description":"Identifies artifact pixels by locating those with intensity values surpassing a user-defined threshold, set as a percentage of the maximum intensity in the image","threshold":threshold}

def gather_image_quality_info(ds):
    # Initialize an empty dictionary to store metadata
    metadata_dict = {
        'PatientInformation': {},
        'StudyInformation': {},
        'SeriesInformation': {},
        'ImageInformation': {},
        'PixelData': {}
    }

    try:

        # Patient Information
        metadata_dict['Patient Information']['Patient Name'] = str(ds.get('PatientName', ''))
        metadata_dict['Patient Information']['Patient ID'] = str(ds.get('PatientID', ''))
        metadata_dict['Patient Information']['Patient Birth Date'] = str(ds.get('PatientBirthDate', ''))
        metadata_dict['Patient Information']['Patient Sex'] = str(ds.get('PatientSex', ''))

        # Study Information
        metadata_dict['Study Information']['Study Instance UID'] = str(ds.get('StudyInstanceUID', ''))
        metadata_dict['Study Information']['Study Date'] = str(ds.get('StudyDate', ''))
        metadata_dict['Study Information']['Study Time'] = str(ds.get('StudyTime', ''))
        metadata_dict['Study Information']['Accession Number'] = str(ds.get('AccessionNumber', ''))
        metadata_dict['Study Information']['Body Part Examined'] = ds.get('BodyPartExamined​', [])

        # Series Information
        metadata_dict['Series Information']['Series Instance UID'] = str(ds.get('SeriesInstanceUID', ''))
        metadata_dict['Series Information']['Modality'] = str(ds.get('Modality', ''))
        metadata_dict['Series Information']['Series Description'] = str(ds.get('SeriesDescription', ''))

        # Image Information
        metadata_dict['Image Information']['Image Type'] = ds.get('ImageType', [])
        metadata_dict['Image Information']['Instance Number'] = str(ds.get('InstanceNumber', ''))
        metadata_dict['Image Information']['Image Position'] = ds.get('ImagePositionPatient', [])
        metadata_dict['Image Information']['Image Orientation'] = ds.get('ImageOrientationPatient', [])
        metadata_dict['Image Information']['Pixel Spacing'] = ds.get('PixelSpacing', [])
        metadata_dict['Image Information']['View Position'] = ds.get('ViewPosition', [])
        metadata_dict['Image Information']['Photometric Interpretation'] = ds.get('PhotometricInterpretation', [])
        

        # Pixel Data
        metadata_dict['Pixel Data']['Bits Allocated'] = int(ds.get('BitsAllocated', 0))
        metadata_dict['Pixel Data']['Bits Stored'] = int(ds.get('BitsStored', 0))
        metadata_dict['Pixel Data']['High Bit'] = int(ds.get('HighBit', 0))
        metadata_dict['Pixel Data']['Pixel Representation'] = int(ds.get('PixelRepresentation', 0))

    except Exception as e:
        print(f"Error processing DICOM file: {e}")

    return metadata_dict