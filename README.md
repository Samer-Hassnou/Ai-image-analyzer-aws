## **AI Image Analyzer**

The **AI Image Analyzer** application is a comprehensive solution for image analysis that is built entirely on a serverless cloud infrastructure on **AWS**. It allows users to upload images via a web interface, and the backend utilizes **Amazon Rekognition** to extract labels and descriptive tags from the image.

-----

### **Key Features**

  * **Serverless Backend:** The backend is built entirely with AWS services, including **AWS Lambda**, **API Gateway**, **S3**, and **DynamoDB**, ensuring high scalability and cost-efficiency.
  * **AI-Powered Analysis:** The system relies on **Amazon Rekognition**, a robust computer vision service, to provide accurate image analysis.
  * **Usage Quota System:** The application implements a daily analysis limit of 3 per user, with tracking and management handled by a **DynamoDB** database.
  * **Multi-Language UI:** The user interface supports English, German, and Arabic to provide a global user experience.
  * **Client-Side Optimization:** Images are compressed on the client-side before being uploaded, which reduces loading times and data consumption.
  * **Enhanced Label Processing:** The frontend translates the extracted labels using **Wikidata** and merges similar concepts to present clearer and more useful results.
  * **Infrastructure as Code (IaC):** The entire AWS infrastructure is automatically defined and deployed using **Terraform**, ensuring consistency and ease of deployment.

-----

### **System Architecture**

The system operates as follows:

1.  A user selects an image via the web interface (`analyzer.html`).
2.  The browser sends the image to an **API Gateway** endpoint.
3.  **API Gateway** triggers an **AWS Lambda** function.
4.  The **Lambda** function checks the user's daily quota in a **DynamoDB** table.
5.  If the quota is available, the function uses **Amazon Rekognition** to analyze the image.
6.  The analysis results are returned to the browser and displayed to the user.

-----

### **Deployment Guide**

#### **Prerequisites**

  * An active AWS Account.
  * Terraform (version 1.4.0 or higher) installed.
  * AWS CLI installed and configured with your credentials.

#### **Steps**

1.  **Prepare the Lambda Function:** The backend logic for the Lambda function (e.g., in a file like `app.py`) is not included in this project. You must create it. The handler must be named `app.lambda_handler`, and the function needs to read environment variables such as `QUOTA_TABLE` and `QUOTA_LIMIT`. Once your Python code is ready, create a ZIP archive named `lambda.zip` containing the script and any dependencies.

2.  **Deploy the AWS Infrastructure:** Place the `lambda.zip` file in the same directory as the `main.tf` file. Open your terminal and run the following commands:

    ```sh
    terraform init
    terraform apply
    ```

    Confirm the deployment by typing `yes`. After the deployment is complete, Terraform will output the **API Gateway** URL. Copy this URL.

3.  **Configure the Frontend:** Open the `analyzer.html` file. Find and replace the following line with the API Gateway URL you copied from the Terraform output:

    ```javascript
    const API_ENDPOINT = 'https:// Chang it to your/analyze';
    ```

4.  **Host the Frontend:** The `analyzer.html` file is a static page. You can host it anywhere, such as on **AWS S3** (with static website hosting enabled), **AWS Amplify**, or any other web hosting service. Once hosted, you can access the URL to use the application.
.