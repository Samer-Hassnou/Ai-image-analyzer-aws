## **AI Image Analyzer**

Die **AI Image Analyzer**-Anwendung ist eine umfassende Lösung für die Bildanalyse, die vollständig auf einer **Serverless**-Cloud-Infrastruktur auf **AWS** basiert. Sie ermöglicht es Benutzern, Bilder über eine Weboberfläche hochzuladen, woraufhin das Backend **Amazon Rekognition** nutzt, um Labels und beschreibende Tags aus dem Bild zu extrahieren.

-----

### **Hauptmerkmale**

  * **Serverless-Backend:** Das Backend wurde vollständig mit AWS-Diensten wie **AWS Lambda**, **API Gateway**, **S3** und **DynamoDB** aufgebaut, was eine hohe Skalierbarkeit und Kosteneffizienz gewährleistet.
  * **KI-gestützte Analyse:** Das System verwendet **Amazon Rekognition**, einen leistungsstarken Computer-Vision-Dienst, um eine präzise Bildanalyse zu ermöglichen.
  * **Nutzungskontingent:** Die Anwendung implementiert ein tägliches Limit von 3 Analysen pro Benutzer. Dieses Kontingent wird über eine **DynamoDB**-Datenbank verwaltet und nachverfolgt.
  * **Mehrsprachige Benutzeroberfläche:** Die Benutzeroberfläche unterstützt Englisch, Deutsch und Arabisch, um eine globale Benutzererfahrung zu bieten.
  * **Client-seitige Optimierung:** Bilder werden vor dem Hochladen auf der Client-Seite komprimiert, was Ladezeiten und Datenverbrauch reduziert.
  * **Verbesserte Label-Verarbeitung:** Das Frontend übersetzt die extrahierten Labels mithilfe von **Wikidata** und führt ähnliche Konzepte zusammen, um klarere und nützlichere Ergebnisse zu liefern.
  * **Infrastruktur als Code (IaC):** Die gesamte AWS-Infrastruktur wird automatisch mit **Terraform** definiert und bereitgestellt, was Konsistenz und eine einfache Bereitstellung gewährleistet.

-----

### **Systemarchitektur**

Das System funktioniert wie folgt:

1.  Ein Benutzer wählt über die Weboberfläche (`analyzer.html`) ein Bild aus.
2.  Der Browser sendet das Bild an einen **API Gateway**-Endpunkt.
3.  Das **API Gateway** löst eine **AWS Lambda**-Funktion aus.
4.  Die **Lambda**-Funktion überprüft das tägliche Kontingent des Benutzers in einer **DynamoDB**-Tabelle.
5.  Falls das Kontingent verfügbar ist, nutzt die Funktion **Amazon Rekognition** zur Bildanalyse.
6.  Die Analyseergebnisse werden an den Browser zurückgegeben und dem Benutzer angezeigt.

-----

### **Bereitstellungsanleitung**

#### **Voraussetzungen**

  * Ein aktives AWS-Konto.
  * Terraform (Version 1.4.0 oder höher) ist installiert.
  * AWS CLI ist installiert und mit Ihren Anmeldeinformationen konfiguriert.

#### **Schritte**

1.  **Lambda-Funktion vorbereiten:** Die Backend-Logik für die Lambda-Funktion (z. B. in einer Datei wie `app.py`) ist nicht in diesem Projekt enthalten. Sie müssen diese selbst erstellen. Der Handler muss `app.lambda_handler` heißen, und die Funktion muss Umgebungsvariablen wie `QUOTA_TABLE` und `QUOTA_LIMIT` lesen können. Sobald Ihr Python-Code fertig ist, erstellen Sie ein ZIP-Archiv namens `lambda.zip`, das das Skript und alle Abhängigkeiten enthält.

2.  **AWS-Infrastruktur bereitstellen:** Legen Sie die Datei `lambda.zip` in dasselbe Verzeichnis wie die Datei `main.tf`. Öffnen Sie Ihr Terminal und führen Sie die folgenden Befehle aus:

    ```sh
    terraform init
    terraform apply
    ```

    Bestätigen Sie die Bereitstellung, indem Sie `yes` eingeben. Nach Abschluss der Bereitstellung gibt Terraform die URL des **API Gateway** aus. Kopieren Sie diese URL.

3.  **Frontend konfigurieren:** Öffnen Sie die Datei `analyzer.html`. Suchen Sie die folgende Zeile und ersetzen Sie die Platzhalter-URL durch die API Gateway-URL, die Sie aus der Terraform-Ausgabe kopiert haben:

    ```javascript
    const API_ENDPOINT = 'https:// Change it to your/analyze';
    ```

4.  **Frontend hosten:** Die Datei `analyzer.html` ist eine statische Seite. Sie können sie überall hosten, zum Beispiel auf **AWS S3** (mit aktivierter statischer Website-Hosting-Funktion), **AWS Amplify** oder einem anderen Webhosting-Dienst. Sobald sie gehostet ist, können Sie die URL aufrufen, um die Anwendung zu nutzen...