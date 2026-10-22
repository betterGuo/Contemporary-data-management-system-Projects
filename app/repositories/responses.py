def find_submission(db, survey_id, respondent_key, submission_key):
    return db.responses.find_one({"surveyId": survey_id, "respondentKey": respondent_key, "submissionKey": submission_key})


def insert_response(db, response):
    return db.responses.insert_one(response)
