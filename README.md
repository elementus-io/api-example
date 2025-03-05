# api-example

Elementus API defnition https://attribution-api.elementus.io/swagger-ui

## Project Setup

### Creating and Populating the .env File

1. In the root directory of the project, create a new file named `.env`.
2. Open the `.env` file and add the following environment variables:

    ```plaintext
    GBQ_URI=<Google Big Query project URI>
    ELEMENTUS_API_KEY=your_api_key_here
    OPENAI_API_KEY=your_api_key_here
    TELEGRAM_TOKEN=your_api_key_here
    TELEGRAM_CHANNEL_ID=<Telegram Channel ID>
    ```

3. Replace `your_api_key_here` with your actual API key.

4. Save the `.env` file.

Make sure to keep your `.env` file private and do not commit it to version control.