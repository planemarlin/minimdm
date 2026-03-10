# Mini Master Data Managment (miniMDM) requirements specification

miniMDM is a minimal light-weight Master Data Management application featuring a web interface (client) with a database and API interface (server). The application should be open source and all software used/included should also be open source. The application could be deployed in a closed source environment but it shouldn't be a requirement to run the application.

## Technical specification

- Use open source database
- Python should be the main code base
- Use open source web server
- Security first approach
- Data sent over network should be kept to a minimal
- Web application should adapt to screen size

## Non-technical specification

- The application should be open source and follow best practices for open source code base
- Documentation should follow best practice and include
    - README.md
    - Changelog.md
    - docs folder with
        - installation instruction
        - feature documentation
        - list of software used in application
- API end point documentation should be generated and available in API
- Feature/function tests should be created and it should be possible to execute them easily
- Application language should be English but values entered should accept any language (Unicode)

## Feature requirements

Implmentation should first focus on the core features and then additional features before moving on the non-prioritized features. Each feature should be implemented with knowledge of the other planned features.

### Core features

- Master Data Management web based application storing values in objects in a database through API end points
- Objects (tables) should be specified in a config file (Yaml/Json) and created/updated from a function
- Insert/updates/deletes of values in objects is done in the web interface
- Bulk import/export of csv/tsv/Json files should be possible
- Log frawework to monitor any changes of values including what, who, when, where and why the changes were made
- Historic values should be saved and versioned
- It should be possible to view historic values and revert to any previous version
- In the web application values should be searchable

### Additional features

- Security - access should be controlled and only given by admins
    - Access by token
    - Access by cloud logins, i.e. Azure Entra Id and similar in AWS and GCP
    - Access by on-prem network logins
    - Access give to users or groups
- Save user preferences
- Use of schema in the database should be a way to group objects to set different access for different users/groups

### Non-prioritized features

- In-application help
- Function to alert when new version is available on Github
- Light mode and dark mode
- Colour variations in web interface
- Mobile app

## Other notes

Further features may be added in the future. The implementation should allow this.
