import boto3
import qrcode
from io import BytesIO
from pathlib import Path
from botocore.exceptions import NoCredentialsError, ClientError
import os, sys

def upload_to_s3_and_generate_qr(file_path, 
                                 bucket_name,
                                 S3_dir
                                 ):
    """
    Uploads a file to AWS S3 and generates a JPG QR code to download it.

    :param file_path: Local path to the file to upload.
    :param bucket_name: Name of the S3 bucket.
    :return: string : "success" or "fail"
    """

    s3_client = boto3.client('s3')     # connect to S3
    
    # 1. Upload file to S3
    object_key = S3_dir+ "/"+ Path(file_path).name    #filename is the last part of the path


    try:
        s3_client.upload_file(file_path, bucket_name, object_key)
        print(f"Upload Successful of {file_path} to s3://{bucket_name}/{object_key}")
    except FileNotFoundError:
        print(f"Error: The file {file_path} was not found.")
        return "fail"
    except NoCredentialsError:
        print("Error: AWS credentials not available.")
        return "fail"
    except ClientError as e:
        print(f"Error uploading to S3: {e}")
        return "fail"


    # 2. Create a QR code image from the download URL
    download_url = "https://"+bucket_name + ".s3.us-east-2.amazonaws.com/" + object_key

    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=5,
            back_color = 'transparent'
        )
        qr.add_data(download_url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        
        # Save as a JPG file
        qr_code_filename = str(file_path).replace("-image.png","-s3_url.jpg")
        img.save(qr_code_filename, "JPEG")
        print(f"QR code image saved as {qr_code_filename}")
        
    except Exception as e:
        print(f"Error generating or saving QR code: {e}")
        return None

    return "success"


if __name__ == '__main__':
    # Look for files in the moveToIdleDisplay folder and upload each one to S3 and create a qr code for it. 
    # Them move the file to the idleDisplayFiles folder, and keep the QR code in the same folder.

    #Define S3 parameters
    s3_bucket_to_store_in = "amzn-s3-speech2picture" 

    for item in Path.iterdir(Path("addToIdleDisplayFiles")):# os.listdir("addToIdleDisplayFiles"):
        path = Path(item)
        qr_image_path = path.parent / path.name.replace("-image.png","-s3_url.jpg")

        if path.is_file() and path.name.endswith("-image.png"):
            result = upload_to_s3_and_generate_qr( file_path = path, bucket_name = s3_bucket_to_store_in, S3_dir= "idleDisplayFiles")
            if result == "success" : 
                # move the image file to the IdleDisplayFiles folder unless it already exists there (in which case, delete it)
                if not os.path.exists(Path("idleDisplayFiles")/path.name):
                    os.rename(path, Path("idleDisplayFiles")/path.name)
                else: os.remove(Path("addToIdleDisplayFiles")/path.name)

                # move the QRcode file to the IdleDisplayFiles folder unless it already exists there (in which case, delete it)
                if not os.path.exists(Path("idleDisplayFiles")/qr_image_path.name):
                    os.rename(qr_image_path, Path("idleDisplayFiles")/qr_image_path.name)
                else: os.remove(Path("addToIdleDisplayFiles")/qr_image_path.name)

            else: print ("failed to upload")
